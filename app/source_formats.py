"""Local vector-to-PNG adapters. Vector units never establish building scale."""
from dataclasses import dataclass
from io import BytesIO
import base64
import math
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote_to_bytes

from PIL import Image


class SourceFormatError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status
        super().__init__(message)


@dataclass
class NormalizedVectorSource:
    pages: list[Image.Image]
    warnings: list[str]
    metadata: dict


IDENTITY = [1., 0., 0., 1., 0., 0.]
_NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?"


def _mul(a, b):
    """SVG affine convention: x'=a*x+c*y+e, y'=b*x+d*y+f."""
    return [a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
            a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
            a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5]]


def _point(matrix, x, y):
    return [matrix[0]*x+matrix[2]*y+matrix[4], matrix[1]*x+matrix[3]*y+matrix[5]]


def _transform(value):
    result = IDENTITY[:]
    for name, args in re.findall(r"([A-Za-z]+)\s*\(([^)]*)\)", value):
        n = [float(x) for x in re.findall(_NUMBER, args)]
        if name == 'matrix' and len(n) == 6:
            part = n
        elif name == 'translate' and len(n) in (1, 2):
            part = [1, 0, 0, 1, n[0], n[1] if len(n) == 2 else 0]
        elif name == 'scale' and len(n) in (1, 2):
            part = [n[0], 0, 0, n[-1], 0, 0]
        elif name == 'rotate' and len(n) in (1, 3):
            angle = math.radians(n[0]); c, s = math.cos(angle), math.sin(angle)
            part = [c, s, -s, c, 0, 0]
            if len(n) == 3:
                part = _mul([1, 0, 0, 1, n[1], n[2]], _mul(part, [1, 0, 0, 1, -n[1], -n[2]]))
        elif name in ('skewX', 'skewY') and len(n) == 1:
            t = math.tan(math.radians(n[0]))
            part = [1, 0, t, 1, 0, 0] if name == 'skewX' else [1, t, 0, 1, 0, 0]
        else:
            raise ValueError('Unsupported transform')
        result = _mul(result, part)
    return result


def _length(value, fallback=None):
    if value is None or value.endswith('%'):
        if fallback is None:
            raise ValueError('Missing viewport size')
        return fallback if value is None else float(value[:-1]) / 100 * fallback
    match = re.fullmatch(r'\s*(' + _NUMBER + r')\s*(px|mm|cm|in|pt|pc|q)?\s*', value, re.I)
    if not match:
        raise ValueError('Unsupported document dimensions')
    factors = {'px': 1, 'mm': 96/25.4, 'cm': 96/2.54, 'in': 96, 'pt': 96/72, 'pc': 16, 'q': 96/101.6}
    return float(match[1]) * factors.get((match[2] or 'px').lower(), 1)


def _viewbox(root):
    raw = root.get('viewBox')
    if raw is None:
        return None
    values = [float(n) for n in re.split(r'[\s,]+', raw.strip())]
    if len(values) != 4 or not all(math.isfinite(n) for n in values) or min(values[2:]) <= 0:
        raise ValueError('Invalid viewBox')
    return values


def _viewport_matrix(box, width, height, aspect):
    x, y, w, h = box
    sx, sy = width/w, height/h
    tokens = aspect.split()
    tokens = [t for t in tokens if t != 'defer']
    align = tokens[0] if tokens else 'xMidYMid'
    if align == 'none':
        return [sx, 0, 0, sy, -x*sx, -y*sy]
    scale = max(sx, sy) if 'slice' in tokens else min(sx, sy)
    dx = (width-w*scale) * (0 if 'xMin' in align else 1 if 'xMax' in align else .5)
    dy = (height-h*scale) * (0 if 'YMin' in align else 1 if 'YMax' in align else .5)
    return [scale, 0, 0, scale, dx-x*scale, dy-y*scale]


def _svg(data, max_edge, *, fill_preview=False):
    from defusedxml import ElementTree as ET
    from cairosvg.surface import PNGSurface
    from cairosvg.parser import Tree
    from xml.etree.ElementTree import tostring

    root = ET.fromstring(data, forbid_entities=True, forbid_external=True)
    if root.tag.split('}')[-1] != 'svg':
        raise ValueError('Not SVG')
    warnings, unsupported, text_records = [], set(), []

    def warn(code):
        unsupported.add(code)

    # Keep the original bytes in the caller's bundle; only this parsed rendering copy is sanitized.
    unsupported_tags = {'script', 'foreignObject', 'animate', 'animateMotion', 'animateTransform', 'set', 'font', 'font-face'}
    for node in root.iter():
        tag = node.tag.split('}')[-1]
        if tag in unsupported_tags:
            warn(tag)
        if tag.startswith('fe') and tag not in ('feBlend', 'feFlood', 'feOffset'):
            warn(tag)
        if tag == 'style' and node.text and re.search(r'@(?:import|font-face)', node.text, re.I):
            warn('external stylesheet/font')
        for name, value in list(node.attrib.items()):
            if name.split('}')[-1] == 'href' and value and not value.startswith(('#', 'data:')):
                warn('external resource (network or local file)')
                if tag in ('image', 'use'):
                    node.attrib.pop(name)
            if 'url(' in value and re.search(r'url\(\s*[\'"]?(?!#|data:)', value, re.I):
                warn('external resource (network or local file)')
        if tag == 'text':
            warn('font substitution and advanced text layout may differ')
    if b'xml-stylesheet' in data:
        warn('external stylesheet')

    def local_fetch(url, resource_type):
        # Embedded PNG/JPEG bytes are self-contained. Never delegate to urllib or open().
        if url.startswith(('data:image/png;', 'data:image/jpeg;')):
            header, payload = url.split(',', 1)
            return base64.b64decode(payload, validate=True) if ';base64' in header else unquote_to_bytes(payload)
        warn('external or unsupported embedded resource (not fetched)')
        return b'<svg xmlns="http://www.w3.org/2000/svg"/>' if resource_type == 'image/svg+xml' else b''

    # CairoSVG's computed nodes apply selector cascade and inline CSS exactly as rendering does.
    original_root = root
    root = Tree(bytestring=tostring(original_root), url_fetcher=local_fetch)
    box = _viewbox(root)
    width = _length(root.get('width'), box[2] if box else None)
    height = _length(root.get('height'), box[3] if box else None)
    if not all(math.isfinite(n) and n > 0 for n in (width, height)):
        raise ValueError('Invalid SVG size')
    box = box or [0., 0., width, height]
    scale = max_edge/max(width, height) if fill_preview else min(1., max_edge/max(width, height))
    output_width, output_height = max(1, round(width*scale)), max(1, round(height*scale))
    matrix = _mul([1/output_width, 0, 0, 1/output_height, 0, 0],
                  _viewport_matrix(box, output_width, output_height, root.get('preserveAspectRatio', 'xMidYMid meet')))
    def walk(node, parent_matrix, ancestors, viewport):
        tag = node.tag.split('}')[-1]
        attrs = dict(node.xml_tree.attrib)
        try:
            if node.get('transform-origin'):
                raise ValueError('Transform origin needs renderer-specific mapping')
            local = _transform(node.get('transform', ''))
        except ValueError:
            local = None
            warn('unsupported transform mapping; affected vector coordinates are unavailable')
        child_viewport = viewport
        if tag == 'svg' and node is not root:
            w = _length(node.get('width'), viewport[0]); h = _length(node.get('height'), viewport[1])
            x = _length(node.get('x', '0'), viewport[0]); y = _length(node.get('y', '0'), viewport[1])
            vb = _viewbox(node) or [0, 0, w, h]
            local = _mul(local, _mul([1, 0, 0, 1, x, y], _viewport_matrix(vb, w, h, node.get('preserveAspectRatio', 'xMidYMid meet')))) if local else None
            child_viewport = (vb[2], vb[3])
        current = _mul(parent_matrix, local) if parent_matrix and local else None
        if tag == 'text':
            record = {'element_id': node.get('id'), 'text': ''.join(node.xml_tree.itertext()),
                      'attributes': attrs, 'ancestor_transforms': ancestors,
                      'local_to_normalized': current, 'bbox': None}
            # An anchor is not a text extent; list-valued glyph positioning remains in attributes.
            try:
                x = float(node.get('x', '0')); y = float(node.get('y', '0'))
                record['normalized_anchor'] = _point(current, x, y) if current else None
            except ValueError:
                record['normalized_anchor'] = None
            text_records.append(record)
        chain = ancestors + ([node.get('transform')] if node.get('transform') else [])
        for child in node.children:
            walk(child, current, chain, child_viewport)

    walk(root, matrix, [], (box[2], box[3]))

    png = PNGSurface.convert(bytestring=tostring(original_root), output_width=output_width,
                             output_height=output_height, background_color='white', url_fetcher=local_fetch)
    with Image.open(BytesIO(png)) as image:
        result = image.convert('RGB')
    if unsupported:
        warnings.append('SVG rendering limitations: ' + '; '.join(sorted(unsupported)) + '. Original vector bytes are retained.')
    metadata = {'format': 'svg', 'physical_scale_established': False, 'pages': [{
        'source_page': 1, 'width': result.width, 'height': result.height,
        'original_bounds': box, 'bounds_convention': 'x,y,width,height', 'viewport': [width, height],
        'document_dimensions': {'width': original_root.get('width'), 'height': original_root.get('height')},
        'effective_dimensions': {'width': root.get('width'), 'height': root.get('height')},
        'preserve_aspect_ratio': root.get('preserveAspectRatio', 'xMidYMid meet'),
        'source_to_normalized': (_mul(matrix, _transform(root.get('transform', '')))
                                 if not root.get('transform-origin') else None), 'text': text_records,
        'unsupported_features': sorted(unsupported)}]}
    return NormalizedVectorSource([result], warnings, metadata)


def _dxf(data, max_edge):
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, svg
    from ezdxf import bbox
    from ezdxf.addons import acadctb

    with tempfile.TemporaryDirectory(prefix='blueprint-vector-') as directory:
        path = Path(directory) / 'source.dxf'
        path.write_bytes(data)
        doc = ezdxf.readfile(path)
    pages, metadata_pages, warnings, unrendered_layouts = [], [], [], []
    layer_records = [{'name': layer.dxf.name, 'off': layer.is_off(), 'frozen': layer.is_frozen()} for layer in doc.layers]
    for source_layout in doc.layouts:
        if not len(source_layout):
            continue
        skipped, external_resources = [], []

        class LocalRenderContext(RenderContext):
            @staticmethod
            def _load_plot_style_table(reference):
                # This runs during construction, layout selection AND viewport copies.
                # Never send any source-selected string through acadctb.load/open().
                if isinstance(reference, str):
                    if reference:
                        entry = {'kind': 'plot_style', 'reference': reference, 'status': 'not_fetched'}
                        if entry not in external_resources:
                            external_resources.append(entry)
                    reference = acadctb.new_ctb()
                return RenderContext._load_plot_style_table(reference)

        class LocalFrontend(Frontend):
            def skip_entity(self, entity, msg):
                skipped.append({'handle': entity.dxf.get('handle'), 'type': entity.dxftype(), 'reason': str(msg)})

            def draw_image_entity(self, entity, properties):
                self.skip_entity(entity, 'External image references are not fetched.')

        backend = svg.SVGBackend()
        settings = config.Configuration(background_policy=config.BackgroundPolicy.WHITE, lineweight_policy=config.LineweightPolicy.RELATIVE)
        LocalFrontend(LocalRenderContext(doc), backend, config=settings).draw_layout(source_layout)
        render_bounds = backend.player().bbox()
        if not render_bounds.has_data or min(render_bounds.size) <= 0:
            warnings.append(f'DXF layout {source_layout.name}: no renderable two-dimensional extent; source records retained.')
            unrendered_layouts.append({'layout': source_layout.name, 'unsupported_entities': skipped, 'external_resources': external_resources,
                                       'entities': [{'handle': e.dxf.get('handle'), 'type': e.dxftype(), 'layer': e.dxf.get('layer')} for e in source_layout]})
            continue
        rendered = backend.get_string(layout.Page(0, 0), settings=layout.Settings(scale=1, fit_page=False))
        normalized = _svg(rendered.encode(), max_edge, fill_preview=True)
        page_meta = normalized.metadata['pages'][0]
        transform = backend.transformation_matrix
        origin, x, y = [transform.transform(p) for p in [(0, 0, 0), (1, 0, 0), (0, 1, 0)]]
        dxf_to_svg = [x.x-origin.x, x.y-origin.y, y.x-origin.x, y.y-origin.y, origin.x, origin.y]
        matrix = _mul(page_meta['source_to_normalized'], dxf_to_svg)
        entities, text = [], []
        for entity in source_layout:
            record = {'handle': entity.dxf.get('handle'), 'type': entity.dxftype(), 'layer': entity.dxf.get('layer')}
            try:
                bounds = bbox.extents([entity])
                if bounds.has_data:
                    record['source_bbox'] = [bounds.extmin.x, bounds.extmin.y, bounds.extmax.x, bounds.extmax.y]
            except (ValueError, TypeError, ezdxf.DXFError):
                pass
            entities.append(record)
            if entity.dxftype() in ('TEXT', 'MTEXT', 'ATTRIB', 'ATTDEF'):
                value = entity.plain_text() if hasattr(entity, 'plain_text') else entity.dxf.get('text', '')
                text.append({**record, 'text': value})
            if entity.dxftype() in ('3DSOLID', 'BODY', 'REGION', 'OLE2FRAME', 'UNDERLAY', 'PDFUNDERLAY', 'DGNUNDERLAY', 'DWFUNDERLAY'):
                skipped.append({**record, 'reason': 'Unsupported or schematic 2D rendering.'})
            if entity.dxftype() == 'INSERT':
                block = doc.blocks.get(entity.dxf.name)
                if block is not None and block.block.is_xref:
                    skipped.append({**record, 'reason': 'External reference is not fetched.'})
        page_meta.update({'source_page': len(pages)+1, 'layout': source_layout.name,
                         'source_to_normalized': matrix,
                         'original_bounds': [render_bounds.extmin.x, render_bounds.extmin.y, render_bounds.extmax.x, render_bounds.extmax.y],
                         'bounds_convention': 'xmin,ymin,xmax,ymax', 'stroke_weights': 'relative_display', 'text': text,
                         'entities': entities, 'unsupported_entities': skipped, 'external_resources': external_resources})
        pages.extend(normalized.pages); metadata_pages.append(page_meta)
        if external_resources:
            warnings.append(f'DXF layout {source_layout.name}: external plot styles were not fetched; default display styles used and original references retained.')
        if skipped:
            warnings.append(f'DXF layout {source_layout.name}: {len(skipped)} unsupported or omitted entity records; inspect source metadata.')
    if not pages:
        raise SourceFormatError('DXF has no renderable 2D layout. Original CAD content requires a supported plan export.', 415)
    warnings.append('DXF previews are 2D top views with relative display stroke weights, not a measured plot scale. 3D view orientation, ACIS solids, external references and some text formatting are unsupported; original layers, units and entity references are retained. Drawing units do not establish building calibration.')
    return NormalizedVectorSource(pages, warnings, {'format': 'dxf', 'physical_scale_established': False,
        'declared_units': {'insunits': int(doc.header.get('$INSUNITS', 0)), 'measurement': doc.header.get('$MEASUREMENT')},
        'layers': layer_records, 'unrendered_layouts': unrendered_layouts, 'pages': metadata_pages})


def dwg_conversion_status():
    """Availability assessment only; no untested converter is advertised as supported."""
    converters = {name: bool(shutil.which(name)) for name in ('ODAFileConverter', 'dwg2dxf')}
    return {'supported': False, 'available_converters': converters,
            'reason': 'DWG conversion is not configured or validated. Export SVG, DXF or PDF.'}


def normalize_vector_source(data: bytes, filename: str, *, max_edge: int = 4096) -> NormalizedVectorSource:
    """Normalize a vector upload; caller retains exact bytes and enforces existing upload/page limits."""
    suffix = Path(filename).suffix.lower()
    if suffix == '.dwg' or data.startswith(b'AC10'):
        raise SourceFormatError(dwg_conversion_status()['reason'], 415)
    try:
        if suffix == '.dxf' or data.startswith(b'AutoCAD Binary DXF'):
            return _dxf(data, max_edge)
        if suffix == '.svg' or data.lstrip().startswith((b'<svg', b'<?xml')):
            return _svg(data, max_edge)
        raise SourceFormatError('Only SVG and DXF are supported by the vector adapter.', 415)
    except SourceFormatError:
        raise
    except ImportError:
        raise SourceFormatError('Vector rendering dependencies are unavailable. Run the project bootstrap script.', 503) from None
    except Exception:
        raise SourceFormatError('Could not render this vector file. Check its dimensions and syntax; external XML entities are not supported.') from None
