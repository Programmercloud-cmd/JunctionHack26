"""Deterministic IFC assembly from source-linked descriptions, never model code."""
import base64
import hashlib
import json
import math
import uuid

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.guid
from shapely.geometry import Polygon

from .artifact_schema import ARTIFACT_MARKER, DISPLAY_UNIT, MANIFEST_PROPERTY, PSET_NAME, ArtifactManifest, EmbeddedPage
from .building import BuildingDescription
from .documents import Document, DocumentError
from .ifc_import import MAX_ELEMENTS, MAX_IFC_BYTES, MAX_TRIANGLES
from .scene import Assumption, Scene, SceneElement, SceneFloor, SourceRef


def _point(point):
    return len(point) == 2 and all(math.isfinite(x) and 0 <= x <= 1 for x in point)


def _region(region, pages, page=None):
    return region.page in pages and (page is None or region.page == page)


def _inside(point, box):
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _bounds(points, page):
    # A line needs a nonzero image region for click-through; expand by one pixel.
    xs, ys = zip(*points)
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    if right == left:
        left, right = max(0, left-1/page.width), min(1, right+1/page.width)
    if bottom == top:
        top, bottom = max(0, top-1/page.height), min(1, bottom+1/page.height)
    return [left, top, right, bottom]


def _transform(matrix, point):
    return [matrix[i][0]*point[0]+matrix[i][1]*point[1]+matrix[i][2] for i in range(2)]


def _floor_frame(floor, page, warnings):
    aspect = page.width / page.height
    box = floor.source.bbox
    calibration = floor.calibration
    known = bool(calibration and math.isfinite(calibration.length_m) and calibration.length_m > 0
                 and _region(calibration.source, {page.number:page}, page.number)
                 and len(calibration.segment) == 2 and all(_point(p) and _inside(p,box) for p in calibration.segment))
    distance = 0
    if known:
        p, q = calibration.segment
        distance = math.hypot(aspect*(p[0]-q[0]), p[1]-q[1])
        known = distance > 0
    if calibration and not known:
        warnings.append(f"{floor.label}: invalid calibration omitted; scale remains unknown.")
    factor = calibration.length_m/distance if known else 10/max(aspect*(box[2]-box[0]), box[3]-box[1])
    rotation = floor.rotation_degrees if floor.rotation_degrees is not None and floor.orientation_basis.strip() else 0
    if not math.isfinite(rotation):
        rotation = 0
    angle = math.radians(rotation)
    c, s = math.cos(angle)*factor, math.sin(angle)*factor
    center = [(box[0]+box[2])/2, (box[1]+box[3])/2]
    matrix = [[c*aspect, s, 0], [s*aspect, -c, 0], [0,0,1]]
    for row in matrix[:2]:
        row[2] = -row[0]*center[0]-row[1]*center[1]
    if not all(math.isfinite(v) for row in matrix for v in row):
        raise DocumentError("The supplied floor scale cannot produce finite geometry.",422)
    return matrix, known, rotation


class _Builder:
    def __init__(self, artifact_id, metric):
        self.namespace = uuid.UUID(artifact_id)
        self.model = ifcopenshell.file(schema="IFC4")
        self.model.header.file_name.time_stamp = "1970-01-01T00:00:00"
        self.model.header.file_name.name = "blueprint-derived.ifc"
        self.elements = []
        self.products = []
        self.origin = self.model.create_entity("IfcAxis2Placement3D",Location=self.point([0,0,0]))
        self.placement = self.model.create_entity("IfcLocalPlacement",RelativePlacement=self.origin)
        self.context = self.model.create_entity("IfcGeometricRepresentationContext",ContextType="Model",CoordinateSpaceDimension=3,
                                              Precision=1e-7,WorldCoordinateSystem=self.origin)
        if metric:
            unit = self.model.create_entity("IfcSIUnit",UnitType="LENGTHUNIT",Name="METRE")
        else:
            unit = self.model.create_entity("IfcContextDependentUnit",Dimensions=self.model.create_entity("IfcDimensionalExponents",1,0,0,0,0,0,0),
                                           UnitType="LENGTHUNIT",Name=DISPLAY_UNIT)
        self.project = self.model.create_entity("IfcProject",GlobalId=self.guid("project"),Name="Drawing-derived visualization",
            Description=ARTIFACT_MARKER,RepresentationContexts=[self.context],UnitsInContext=self.model.create_entity("IfcUnitAssignment",Units=[unit]))
        self.building = self.model.create_entity("IfcBuilding",GlobalId=self.guid("building"),Name="Depicted building",
            ObjectPlacement=self.placement,CompositionType="ELEMENT")
        self.aggregate(self.project,[self.building],"building")

    def guid(self, key):
        return ifcopenshell.guid.compress(uuid.uuid5(self.namespace,key).hex)

    def point(self, coordinates):
        return self.model.create_entity("IfcCartesianPoint",Coordinates=[float(v) for v in coordinates])

    def aggregate(self, parent, children, key):
        self.model.create_entity("IfcRelAggregates",GlobalId=self.guid("aggregate:"+key),RelatingObject=parent,RelatedObjects=children)

    def pset(self, entity, name, values, key):
        props = [self.model.create_entity("IfcPropertySingleValue",Name=k,NominalValue=self.model.create_entity("IfcText",v)) for k,v in values.items()]
        pset = self.model.create_entity("IfcPropertySet",GlobalId=self.guid("pset:"+key),Name=name,HasProperties=props)
        self.model.create_entity("IfcRelDefinesByProperties",GlobalId=self.guid("property:"+key),RelatedObjects=[entity],RelatingPropertyDefinition=pset)

    def solid(self, points, z, height):
        curve = self.model.create_entity("IfcPolyline",Points=[self.point(p) for p in points+[points[0]]])
        profile = self.model.create_entity("IfcArbitraryClosedProfileDef",ProfileType="AREA",OuterCurve=curve)
        position = self.model.create_entity("IfcAxis2Placement3D",Location=self.point([0,0,z]))
        solid = self.model.create_entity("IfcExtrudedAreaSolid",SweptArea=profile,Position=position,
            ExtrudedDirection=self.model.create_entity("IfcDirection",DirectionRatios=[0.,0.,1.]),Depth=float(height))
        shape = self.model.create_entity("IfcShapeRepresentation",ContextOfItems=self.context,RepresentationIdentifier="Body",
                                         RepresentationType="SweptSolid",Items=[solid])
        return self.model.create_entity("IfcProductDefinitionShape",Representations=[shape])

    def product(self, ifc_type, key, name, polygon, z, height, storey, source, assumptions, basis="observed", note="", kind=None):
        if len(self.elements) >= MAX_ELEMENTS:
            raise DocumentError(f"Generated IFC exceeds the {MAX_ELEMENTS:,}-element limit; no inventory was truncated.",413)
        entity = self.model.create_entity(ifc_type,GlobalId=self.guid(key),Name=name,ObjectPlacement=self.placement,
                                          Representation=self.solid(polygon,z,height))
        self.products.append(entity)
        scene = SceneElement(id=entity.GlobalId,kind=kind or {"IfcSpace":"room","IfcWall":"wall","IfcDoor":"door","IfcWindow":"window"}[ifc_type],
            name=name,ifc_type=ifc_type,storey_id=storey.GlobalId,source=source,assumptions=assumptions,
            geometry_origin="inferred",geometry=None,evidence_basis=basis,note=note)
        self.elements.append(scene)
        self.pset(entity,PSET_NAME,{"Source":source.model_dump_json(),"Assumptions":json.dumps([a.model_dump() for a in assumptions]),
                  "EvidenceBasis":basis,"Note":note,"ArtifactMarker":ARTIFACT_MARKER},key)
        return entity


def _rectangle(start, end, thickness):
    dx,dy = end[0]-start[0],end[1]-start[1]
    length = math.hypot(dx,dy)
    nx,ny = -dy/length*thickness/2,dx/length*thickness/2
    return [[start[0]+nx,start[1]+ny],[end[0]+nx,end[1]+ny],[end[0]-nx,end[1]-ny],[start[0]-nx,start[1]-ny]]


def _assumption(prop, value, unit, reason):
    return Assumption(property=prop,value=value,unit=unit,reason=reason)


def generate_ifc(description: BuildingDescription, document: Document) -> bytes:
    description = BuildingDescription.model_validate(description)
    pages = {p.number:p for p in document.pages}
    warnings = list(description.limitations)
    if not description.floors or any(not _region(f.source,pages) for f in description.floors):
        raise DocumentError("The building description needs depicted floors on available source pages.",422)
    frames = [_floor_frame(f,pages[f.source.page],warnings) for f in description.floors]
    metric = all(known for _,known,_ in frames)
    # Registration requires a common evidenced anchor AND compatible supported scales.
    aligned = metric and all(f.alignment and f.alignment.group.strip() and f.alignment.basis.strip()
        and _region(f.alignment.source,pages,f.source.page) and _point(f.alignment.anchor)
        and _inside(f.alignment.anchor,f.source.bbox) and f.rotation_degrees is not None
        and f.orientation_basis.strip() for f in description.floors)
    aligned = bool(aligned and len({f.alignment.group for f in description.floors}) == 1)
    artifact_id = str(uuid.uuid5(uuid.NAMESPACE_URL,"blueprintqa:"+document.id))
    builder = _Builder(artifact_id,metric)
    floors = []
    room_count = 0
    for floor_index,(floor,(matrix,known,rotation)) in enumerate(zip(description.floors,frames),start=1):
        prefix = f"floor:{floor_index}"
        page = pages[floor.source.page]
        unit = "m" if known else "relative"
        wall_height, wall_thickness, plate_thickness = (2.6,.12,.04) if known else (1.2,.08,.02)
        if aligned:
            anchor = _transform(matrix,floor.alignment.anchor)
            matrix[0][2] -= anchor[0]
            matrix[1][2] -= anchor[1]
        storey = builder.model.create_entity("IfcBuildingStorey",GlobalId=builder.guid(prefix),Name=floor.label,
            ObjectPlacement=builder.placement,CompositionType="ELEMENT",Elevation=None)
        builder.aggregate(builder.building,[storey],prefix)
        floor_source = SourceRef(kind="image",page=page.number,bbox=floor.source.bbox)
        floor_assumptions = [_assumption("elevation",0,unit,"Common display plane only; source storey elevation is unknown."),
            _assumption("layout","aligned" if aligned else "schematic",None,"Supported common anchors" if aligned else "Floor registration is unknown; separate diagrams are not a measured aligned building.")]
        if not known:
            floor_assumptions.append(_assumption("panel_extent",10,"relative","Largest source panel extent normalized to 10 display units; not a physical measurement."))
        if floor.rotation_degrees is None or not floor.orientation_basis.strip():
            floor_assumptions.append(_assumption("orientation","Original page orientation",None,"No supported orientation normalization is available."))
        if floor.order is None or not floor.order_basis.strip():
            floor_assumptions.append(_assumption("order","Source diagram order only",None,"The physical storey order is not established."))
        observations = [text for text in (floor.order_basis,floor.orientation_basis) if text]
        measurements = [m for m in floor.measurements if m.source is None or _region(m.source,pages,page.number)]
        if len(measurements) != len(floor.measurements):
            warnings.append(f"{floor.label}: measurements referencing unavailable/different source pages were omitted.")
        floors.append(SceneFloor(id=storey.GlobalId,label=floor.label,source=floor_source,
            order=floor.order if floor.order_basis.strip() else None,scale_status="known" if known else "unknown",
            rotation_degrees=rotation,alignment_status="supported" if aligned else "schematic",observations=observations,
            assumptions=floor_assumptions,calibration=floor.calibration if known else None,
            alignment=floor.alignment if aligned else None,measurements=measurements,transform=matrix))
        builder.pset(storey,PSET_NAME,{"Source":floor_source.model_dump_json(),"Floor":floors[-1].model_dump_json(),"ArtifactMarker":ARTIFACT_MARKER},prefix)
        valid = {}
        invalid = set()
        for index,room in enumerate(floor.rooms,start=1):
            points = room.polygon
            if len(points)<3 or not all(_point(p) and _inside(p,floor.source.bbox) for p in points):
                invalid.add(index)
                continue
            polygon = Polygon(points)
            if not polygon.is_valid or polygon.area <= 0:
                invalid.add(index)
                continue
            valid[index] = polygon
        conflicts = set()
        for index,polygon in valid.items():
            for other_index,other in valid.items():
                if index < other_index and polygon.intersection(other).area > .1*min(polygon.area,other.area):
                    conflicts.update((index,other_index))
        retained = {index:polygon for index,polygon in valid.items() if index not in conflicts}
        if invalid or conflicts:
            warnings.append(f"{floor.label}: omitted {len(invalid|conflicts)} room footprints ({len(invalid)} invalid, {len(conflicts)} ambiguous overlap participants).")
        if not retained:
            warnings.append(f"{floor.label}: no renderable rooms survived; its depicted floor record is retained.")
        spaces, physical, walls, edges = [], [], {}, {}
        for room_index,polygon in retained.items():
            room_count += 1
            room = floor.rooms[room_index-1]
            points = list(map(list,list(polygon.exterior.coords)[:-1]))
            world = [_transform(matrix,p) for p in points]
            source = SourceRef(kind="image",page=page.number,bbox=list(polygon.bounds))
            key = f"{prefix}:room:{room_index}"
            spaces.append(builder.product("IfcSpace",key,room.label,world,-plate_thickness,plate_thickness,storey,source,
                [_assumption("floor_plate_thickness",plate_thickness,unit,"Display-only thin footprint, not a measured slab."),
                 _assumption("footprint","Approximate image interpretation",None,"Original-page perimeter is a fallible interpretation of source pixels.")],room.basis,room.note))
            for edge_index,(start,end) in enumerate(zip(points,points[1:]+points[:1])):
                if start == end:
                    continue
                edge_key = tuple(sorted((tuple(start),tuple(end))))
                if edge_key not in edges:
                    a,b = _transform(matrix,start),_transform(matrix,end)
                    box = _bounds([start,end],page)
                    floor_box = floor.source.bbox
                    box = [max(box[0],floor_box[0]),max(box[1],floor_box[1]),min(box[2],floor_box[2]),min(box[3],floor_box[3])]
                    edge_source = SourceRef(kind="image",page=page.number,bbox=box)
                    wall = builder.product("IfcWall",f"{key}:edge:{edge_index}",f"Boundary — {room.label}",_rectangle(a,b,wall_thickness),0,wall_height,
                        storey,edge_source,[_assumption("height",wall_height,unit,"Display extrusion; source wall height is not established."),
                        _assumption("thickness",wall_thickness,unit,"Display boundary width; source wall thickness is not established.")],room.basis,room.note)
                    edges[edge_key] = wall
                    physical.append(wall)
                walls[(room_index,edge_index)] = (edges[edge_key],start,end)
        if spaces:
            builder.aggregate(storey,spaces,prefix+":spaces")
        omitted_openings = 0
        openings_seen = set()
        for opening_index,opening in enumerate(floor.openings,start=1):
            host = walls.get((opening.host_room,opening.host_edge))
            if not host or not _region(opening.source,pages,page.number) or len(opening.segment)!=2 or not all(_point(p) for p in opening.segment):
                omitted_openings += 1
                continue
            source_box = opening.source.bbox
            if (not _inside(source_box[:2],floor.source.bbox) or not _inside(source_box[2:],floor.source.bbox)
                    or not all(_inside(p,source_box) for p in opening.segment)):
                omitted_openings += 1
                continue
            wall,start,end = host
            # Only project onto the explicitly named host within its rendered wall band.
            aspect = page.width/page.height
            a,b = [aspect*start[0],start[1]],[aspect*end[0],end[1]]
            dx,dy = b[0]-a[0],b[1]-a[1]
            length2 = dx*dx+dy*dy
            projected = []
            for point in opening.segment:
                p = [aspect*point[0],point[1]]
                t = ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2
                nearest = [a[0]+t*dx,a[1]+t*dy]
                nearest_source = [nearest[0]/aspect,nearest[1]]
                if not 0 <= t <= 1 or math.dist(_transform(matrix,point),_transform(matrix,nearest_source)) > wall_thickness/2:
                    break
                # Projection cannot silently move the opening outside its cited evidence.
                if not (source_box[0]-1e-9 <= nearest_source[0] <= source_box[2]+1e-9
                        and source_box[1]-1e-9 <= nearest_source[1] <= source_box[3]+1e-9):
                    break
                projected.append(nearest_source)
            if len(projected)!=2 or math.dist(*projected)==0:
                omitted_openings += 1
                continue
            duplicate = (wall.GlobalId,tuple(sorted(tuple(round(v,9) for v in p) for p in projected)))
            if duplicate in openings_seen:
                omitted_openings += 1
                continue
            openings_seen.add(duplicate)
            a,b = [_transform(matrix,p) for p in projected]
            key = f"{prefix}:opening:{opening_index}"
            sill,height = ((0,2.1) if opening.kind=="door" else (1,1.2)) if known else ((0,.8) if opening.kind=="door" else (.4,.45))
            void = builder.model.create_entity("IfcOpeningElement",GlobalId=builder.guid(key+":void"),Name="Display opening",
                ObjectPlacement=builder.placement,Representation=builder.solid(_rectangle(a,b,wall_thickness*1.4),sill,height),PredefinedType="OPENING")
            builder.model.create_entity("IfcRelVoidsElement",GlobalId=builder.guid(key+":void-relation"),RelatingBuildingElement=wall,RelatedOpeningElement=void)
            source = SourceRef(kind="image",page=page.number,bbox=opening.source.bbox)
            assumptions = [_assumption("height",height,unit,"Display opening height; not measured from the source."),
                _assumption("sill_height",sill,unit,"Display opening sill; not measured from the source."),
                _assumption("thickness",.03,unit,"Display opening fill thickness."),
                _assumption("host_projection","Within rendered host wall band",None,"Endpoints projected onto the explicitly referenced boundary only within its display half-thickness; source region is unchanged.")]
            fill = builder.product("IfcDoor" if opening.kind=="door" else "IfcWindow",key,opening.label,_rectangle(a,b,.03),sill,height,
                storey,source,assumptions,opening.basis,opening.note)
            physical.append(fill)
            builder.model.create_entity("IfcRelFillsElement",GlobalId=builder.guid(key+":fill-relation"),RelatingOpeningElement=void,RelatedBuildingElement=fill)
        if omitted_openings:
            warnings.append(f"{floor.label}: omitted {omitted_openings} openings with invalid, ambiguous, omitted or duplicate hosts/segments.")
        if physical:
            builder.model.create_entity("IfcRelContainedInSpatialStructure",GlobalId=builder.guid(prefix+":containment"),RelatedElements=physical,RelatingStructure=storey)
    if not room_count:
        raise DocumentError("No valid room footprints survived across the depicted floors; no model was saved.",422)
    warnings.extend(["Drawing-derived visualization: generated geometry and inventory are not factual building evidence.",
        "Wall heights, thicknesses, floor plates and opening vertical dimensions are display assumptions; storey elevations are unknown."])
    if not metric:
        warnings.append("UNSCALED: at least one floor lacks calibration. Project units are relative; mixed-floor distances are not physical measurements.")
    scene = Scene(document_id=document.id,source_kind="image",units="m" if metric else "relative",elements=builder.elements,
        warnings=warnings,catalog_complete=False,derived=True,artifact_id=artifact_id,floors=floors,layout="aligned" if aligned else "schematic")
    if sum(((p.path.stat().st_size+2)//3)*4 for p in document.pages) > MAX_IFC_BYTES:
        raise DocumentError("Embedded source pages would exceed the existing 25 MiB IFC limit; no pages were truncated.",413)
    embedded = []
    for page in document.pages:
        data = page.path.read_bytes()
        embedded.append(EmbeddedPage(number=page.number,width=page.width,height=page.height,sha256=hashlib.sha256(data).hexdigest(),
                                     png_base64=base64.b64encode(data).decode("ascii")))
    manifest = ArtifactManifest(artifact_id=artifact_id,source_filename=document.filename,pages=embedded,scene=scene)
    builder.pset(builder.project,PSET_NAME,{MANIFEST_PROPERTY:manifest.model_dump_json()},"manifest")
    data = builder.model.to_string().encode("utf-8")
    if len(data)>MAX_IFC_BYTES:
        raise DocumentError("Generated IFC including original source pages exceeds the existing 25 MiB limit; nothing was truncated.",413)
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords",True)
    iterator = ifcopenshell.geom.iterator(settings,builder.model,1,include=builder.products)
    triangles = 0
    if iterator.initialize():
        while True:
            triangles += len(iterator.get().geometry.faces)//3
            if triangles>MAX_TRIANGLES:
                raise DocumentError("Generated IFC exceeds the existing 1,000,000-triangle limit.",413)
            if not iterator.next():
                break
    return data
