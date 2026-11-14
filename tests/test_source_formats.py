from io import BytesIO, StringIO
from pathlib import Path
import json

import pytest
from app.source_formats import SourceFormatError, normalize_vector_source, dwg_conversion_status, _point


def svg(content, **attrs):
    defaults = {'width': '200', 'height': '100', **attrs}
    attributes = ' '.join(f'{k}="{v}"' for k, v in defaults.items())
    return f'<svg xmlns="http://www.w3.org/2000/svg" {attributes}>{content}</svg>'.encode()


def test_svg_viewbox_letterbox_and_nested_text_mapping():
    data = svg('<g transform="translate(10,5)"><g transform="scale(2)"><text id="label" x="10" y="20">Office</text></g></g>', viewBox='10 20 100 100')
    result = normalize_vector_source(data, 'plan.svg')
    page = result.metadata['pages'][0]
    assert result.pages[0].size == (200, 100)
    assert _point(page['source_to_normalized'], 10, 20) == pytest.approx([.25, 0])
    assert _point(page['source_to_normalized'], 110, 120) == pytest.approx([.75, 1])
    assert page['text'][0]['normalized_anchor'] == pytest.approx([.35, .25])
    assert page['text'][0]['text'] == 'Office'
    assert page['text'][0]['bbox'] is None
    assert result.metadata['physical_scale_established'] is False
    json.dumps(result.metadata, allow_nan=False)


@pytest.mark.parametrize('aspect,expected', [('none',[0,0]), ('xMaxYMax meet',[.5,0]), ('xMinYMin slice',[0,0])])
def test_svg_aspect_modes(aspect, expected):
    result = normalize_vector_source(svg('<rect x="10" y="20" width="10" height="10"/>', viewBox='10 20 100 100', preserveAspectRatio=aspect), 'a.svg')
    assert _point(result.metadata['pages'][0]['source_to_normalized'],10,20) == pytest.approx(expected)


def test_svg_viewbox_only_and_document_units_are_not_scale():
    raw = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100"><path d="M0 0L300 100"/></svg>'
    result = normalize_vector_source(raw, 'a.svg')
    assert result.pages[0].size == (300, 100)
    metric = normalize_vector_source(svg('<rect width="10" height="10"/>', width='200mm', height='100mm'), 'b.svg', max_edge=500)
    assert metric.pages[0].size == (500,250)
    assert metric.metadata['physical_scale_established'] is False
    assert metric.metadata['pages'][0]['document_dimensions']['width'] == '200mm'


def test_svg_nested_svg_coordinate_mapping():
    result = normalize_vector_source(svg('<svg x="20" y="10" width="80" height="40" viewBox="0 0 40 20"><text x="10" y="10">Lab</text></svg>'), 'a.svg')
    assert result.metadata['pages'][0]['text'][0]['normalized_anchor'] == pytest.approx([.2,.3])


def test_svg_external_resources_never_read_or_fetch(monkeypatch, tmp_path):
    from cairosvg import url
    def fail(*args, **kwargs):
        raise AssertionError('External fetch attempted')
    monkeypatch.setattr(url, 'urlopen', fail)
    secret = tmp_path/'local.svg'; secret.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>DO NOT READ</text></svg>')
    content = f'<style>@import "https://example.invalid/private.css"; @font-face {{font-family: Test; src: url(file://{secret});}}</style><image href="file://{secret}" width="40" height="40"/><use href="https://example.invalid/external.svg#x"/><rect width="10" height="10" fill="black"/>'
    result = normalize_vector_source(svg(content), 'safe.svg')
    assert result.pages[0].getpixel((5,5)) == (0,0,0)
    assert 'external' in ' '.join(result.warnings)
    assert 'DO NOT READ' not in json.dumps(result.metadata)


def test_svg_xml_entities_rejected():
    raw = b'<!DOCTYPE svg [<!ENTITY local SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><text>&local;</text></svg>'
    with pytest.raises(SourceFormatError, match='external XML entities'):
        normalize_vector_source(raw, 'unsafe.svg')


def test_svg_unsupported_features_warn_and_original_text_survives():
    result = normalize_vector_source(svg('<foreignObject/><filter><feGaussianBlur/></filter><text x="4" y="30">Library</text>'), 'a.svg')
    assert 'foreignObject' in result.warnings[0]
    assert 'feGaussianBlur' in result.warnings[0]
    assert result.metadata['pages'][0]['text'][0]['text'] == 'Library'


def test_dxf_units_layers_handles_y_inversion_and_text():
    import ezdxf
    document=ezdxf.new(); document.units=4
    document.layers.new('Walls'); document.layers.new('Labels')
    model=document.modelspace(); line=model.add_line((10,20),(110,70),dxfattribs={'layer':'Walls'})
    model.add_text('Library',dxfattribs={'insert':(20,25),'height':4,'layer':'Labels'})
    stream=StringIO(); document.write(stream)
    result=normalize_vector_source(stream.getvalue().encode(), 'source.dxf')
    assert result.metadata['declared_units']['insunits'] == 4
    assert result.metadata['physical_scale_established'] is False
    assert 'Walls' in [r['name'] for r in result.metadata['layers']]
    page=result.metadata['pages'][0]
    assert page['text'][0]['text'] == 'Library'
    assert line.dxf.handle in [e['handle'] for e in page['entities']]
    assert _point(page['source_to_normalized'],10,20) == pytest.approx([0,1], abs=1e-5)
    assert _point(page['source_to_normalized'],110,70) == pytest.approx([1,0], abs=1e-5)
    json.dumps(result.metadata, allow_nan=False)


def test_dxf_paper_layout_preserved():
    import ezdxf
    document=ezdxf.new(); document.modelspace().add_line((0,0),(100,50))
    paper=document.layouts.new('Plan sheet');paper.add_line((0,0),(50,50))
    stream=StringIO();document.write(stream)
    result=normalize_vector_source(stream.getvalue().encode(),'two.dxf')
    assert len(result.pages)==2
    assert [p['layout'] for p in result.metadata['pages'] if p['source_page']] == ['Model','Plan sheet']


def test_dwg_availability_is_not_claimed_as_support():
    assert dwg_conversion_status()['supported'] is False
    with pytest.raises(SourceFormatError, match='Export SVG, DXF or PDF'):
        normalize_vector_source(b'AC1032 drawing', 'drawing.dwg')


def test_invalid_vector_returns_safe_error():
    with pytest.raises(SourceFormatError):
        normalize_vector_source(b'<svg width="nan" height="100"/>','broken.svg')


def test_svg_root_transform_mapping_matches_render():
    result = normalize_vector_source(svg('<rect x="10" y="10" width="10" height="10"/>', transform='translate(30,20)'), 'root.svg')
    page = result.metadata['pages'][0]
    assert _point(page['source_to_normalized'], 15,15) == pytest.approx([.225,.35])
    assert result.pages[0].getpixel((45,35)) == (0,0,0)


def test_dxf_external_image_is_not_loaded(monkeypatch):
    import ezdxf
    import PIL.Image
    document=ezdxf.new(); model=document.modelspace();model.add_line((0,0),(100,50))
    image=document.add_image_def(filename='/private/missing.png',size_in_pixel=(100,100))
    model.add_image(image_def=image,insert=(0,0),size_in_units=(10,10))
    stream=StringIO();document.write(stream)
    original_open=PIL.Image.open
    def checked_open(fp,*args,**kwargs):
        assert not isinstance(fp,(str,Path)), 'External image read attempted'
        return original_open(fp,*args,**kwargs)
    monkeypatch.setattr(PIL.Image,'open',checked_open)
    result=normalize_vector_source(stream.getvalue().encode(),'image.dxf')
    assert any('not fetched' in e['reason'] for e in result.metadata['pages'][0]['unsupported_entities'])


@pytest.mark.parametrize('style', [
    '<g style="transform:translate(50,20)">{content}</g>',
    '<style>.m {{transform:translate(50,20)}}</style><g class="m">{content}</g>',
    '<style>.m {{transform:translate(50,20) !important}}</style><g class="m" transform="translate(1,1)">{content}</g>',
])
def test_svg_computed_css_transforms_match_pixels(style):
    content = '<rect x="10" y="10" width="10" height="10"/><text x="10" y="10">A</text>'
    result = normalize_vector_source(svg(style.format(content=content)), 'css.svg')
    assert result.pages[0].getpixel((65,35)) == (0,0,0)
    assert result.metadata['pages'][0]['text'][0]['normalized_anchor'] == pytest.approx([.30,.30])


def test_svg_root_css_transform_and_viewport_dimensions():
    data = svg('<rect x="10" y="10" width="10" height="10"/>', style='transform:translate(50,20);width:400px;height:200px')
    result = normalize_vector_source(data, 'root-css.svg')
    assert result.pages[0].size == (400,200)
    assert result.pages[0].getpixel((65,35)) == (0,0,0)
    assert _point(result.metadata['pages'][0]['source_to_normalized'],15,15) == pytest.approx([65/400,35/200])


def test_svg_transform_origin_does_not_claim_exact_mapping():
    result = normalize_vector_source(svg('<text x="10" y="10">A</text>', style='transform:rotate(30deg);transform-origin:50% 50%'), 'origin.svg')
    assert result.metadata['pages'][0]['source_to_normalized'] is None
    assert result.metadata['pages'][0]['text'][0]['normalized_anchor'] is None
    assert 'mapping' in ' '.join(result.warnings)


@pytest.mark.parametrize('scope', ['modelspace','paperspace','viewport'])
def test_dxf_plot_style_never_reads_external_file(scope, monkeypatch, tmp_path):
    import ezdxf
    from ezdxf.addons import acadctb
    document = ezdxf.new()
    model = document.modelspace();model.add_line((0,0),(100,50))
    sentinel = tmp_path/'private.ctb';sentinel.write_bytes(b'not a plot style')
    if scope == 'modelspace':
        model.set_plot_style(str(sentinel))
    else:
        paper = document.layouts.new('Sheet')
        paper.add_line((0,0),(100,50))
        if scope == 'paperspace':
            paper.set_plot_style(str(sentinel))
        else:
            viewport = paper.add_viewport(center=(50,25),size=(100,50),view_center_point=(50,25),view_height=50,status=2)
            viewport.dxf.plot_style_name = str(sentinel)
    stream = StringIO();document.write(stream)
    def deny(*args, **kwargs):
        raise AssertionError('External plot-style read attempted')
    monkeypatch.setattr(acadctb, 'load', deny)
    result = normalize_vector_source(stream.getvalue().encode(), 'plotstyle.dxf', max_edge=200)
    resources = [r for p in result.metadata['pages'] for r in p['external_resources']]
    assert {'kind':'plot_style','reference':str(sentinel),'status':'not_fetched'} in resources
    assert 'external plot styles were not fetched' in ' '.join(result.warnings)
