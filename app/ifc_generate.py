"""Deterministic IFC assembly from source-linked descriptions, never model code."""
import base64
import hashlib
import json
import math
import uuid

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.guid
from collections import Counter
from shapely.geometry import Polygon, LineString, box

from .artifact_schema import ARTIFACT_MARKER, DISPLAY_UNIT, MANIFEST_PROPERTY, PSET_NAME, ArtifactManifest, EmbeddedPage
from .building import BoundaryRegion, BuildingDescription
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
    factor = calibration.length_m/distance if known else 10/max(aspect,1)
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

    def solid_item(self, points, z, height):
        curve = self.model.create_entity("IfcPolyline",Points=[self.point(p) for p in points+[points[0]]])
        profile = self.model.create_entity("IfcArbitraryClosedProfileDef",ProfileType="AREA",OuterCurve=curve)
        position = self.model.create_entity("IfcAxis2Placement3D",Location=self.point([0,0,z]))
        return self.model.create_entity("IfcExtrudedAreaSolid",SweptArea=profile,Position=position,
            ExtrudedDirection=self.model.create_entity("IfcDirection",DirectionRatios=[0.,0.,1.]),Depth=float(height))

    def solid(self, points, z, height):
        solid = self.solid_item(points,z,height)
        shape = self.model.create_entity("IfcShapeRepresentation",ContextOfItems=self.context,RepresentationIdentifier="Body",
                                         RepresentationType="SweptSolid",Items=[solid])
        return self.model.create_entity("IfcProductDefinitionShape",Representations=[shape])

    def stair_symbol(self, entity, points, z, thickness):
        """Flat, level graphic marks: no arrow, ascent, tread count or stair rise claim."""
        footprint=Polygon(points)
        left,bottom,right,top=footprint.bounds
        vertical=top-bottom >= right-left
        span=top-bottom if vertical else right-left
        band=span*.025
        items=list(entity.Representation.Representations[0].Items)
        # These are graphic positions, never a limit on extracted features or source steps.
        for fraction in (.2,.4,.6,.8):
            position=(bottom if vertical else left)+span*fraction
            strip=box(left,position-band/2,right,position+band/2) if vertical else box(position-band/2,bottom,position+band/2,top)
            clipped=footprint.intersection(strip)
            pieces=[clipped] if clipped.geom_type=="Polygon" else list(getattr(clipped,"geoms",[]))
            for piece in pieces:
                if piece.geom_type=="Polygon" and piece.area>0:
                    items.append(self.solid_item(list(map(list,list(piece.exterior.coords)[:-1])),z,thickness))
        entity.Representation.Representations[0].Items=items

    def product(self, ifc_type, key, name, polygon, z, height, storey, source, assumptions, basis="observed", note="", kind=None,
                representation="reconstructed", semantic_type="", environment="unknown"):
        if len(self.elements) >= MAX_ELEMENTS:
            raise DocumentError(f"Generated IFC exceeds the {MAX_ELEMENTS:,}-element limit; no inventory was truncated.",413)
        entity = self.model.create_entity(ifc_type,GlobalId=self.guid(key),Name=name,ObjectPlacement=self.placement,
                                          Representation=self.solid(polygon,z,height) if polygon else None)
        self.products.append(entity)
        scene = SceneElement(id=entity.GlobalId,kind=kind or {"IfcSpace":"room","IfcWall":"wall","IfcDoor":"door","IfcWindow":"window"}[ifc_type],
            name=name,ifc_type=ifc_type,storey_id=storey.GlobalId,source=source,assumptions=assumptions,
            geometry_origin="inferred",geometry=None,evidence_basis=basis,note=note,
            representation=representation,semantic_type=semantic_type or kind or ifc_type,environment=environment)
        self.elements.append(scene)
        self.pset(entity,PSET_NAME,{"Source":source.model_dump_json(),"Assumptions":json.dumps([a.model_dump() for a in assumptions]),
                  "EvidenceBasis":basis,"Note":note,"ArtifactMarker":ARTIFACT_MARKER,
                  "Representation":representation,"SemanticType":scene.semantic_type,"Environment":environment},key)
        return entity


def _rectangle(start, end, thickness):
    return _band(start,end,-thickness/2,thickness/2)


def _band(start,end,low,high):
    dx,dy = end[0]-start[0],end[1]-start[1]
    length = math.hypot(dx,dy)
    nx,ny = -dy/length,dx/length
    return [[start[0]+nx*high,start[1]+ny*high],[end[0]+nx*high,end[1]+ny*high],
            [end[0]+nx*low,end[1]+ny*low],[start[0]+nx*low,start[1]+ny*low]]


def _depicted_band(boundary,floor,page,matrix):
    """Signed source-face offsets, tested before rotation/translation can lose a contact."""
    width_segment=boundary.thickness_segment
    if (len(width_segment)!=2 or not all(_point(p) and _inside(p,boundary.source.bbox)
            and _inside(p,floor.source.bbox) for p in width_segment)):
        return None
    aspect=page.width/page.height
    plane=lambda p:[aspect*p[0],-p[1]]
    a,b=[plane(p) for p in boundary.segment[:2]]
    p,q=[plane(p) for p in width_segment]
    axis=[b[i]-a[i] for i in (0,1)]
    cross=[q[i]-p[i] for i in (0,1)]
    if (math.dist(p,q)==0 or not math.isclose(sum(x*y for x,y in zip(axis,cross)),0,abs_tol=1e-8)
            or not LineString(width_segment).intersects(LineString(boundary.segment[:2]))):
        return None
    length=math.hypot(*axis)
    normal=[-axis[1]/length,axis[0]/length]
    factor=math.hypot(matrix[0][1],matrix[1][1])
    offsets=sorted(sum((point[i]-a[i])*normal[i] for i in (0,1))*factor for point in (p,q))
    return offsets if offsets[1]>offsets[0] else None


def _assumption(prop, value, unit, reason):
    return Assumption(property=prop,value=value,unit=unit,reason=reason)


def _valid_polygon(points, box):
    if len(points)<3 or not all(_point(p) and _inside(p,box) for p in points):
        return None
    polygon=Polygon(points)
    return polygon if polygon.is_valid and polygon.area>0 else None


def _item_source(region, points, floor, page):
    """Return source and whether precise localization is trustworthy."""
    if region is not None:
        cited=region.bbox
        panel=floor.source.bbox
        if (isinstance(region,BoundaryRegion) and region.page==page.number
                and (cited[0]==cited[2] or cited[1]==cited[3]) and len(points)>=2
                and all(_point(p) and _inside(p,cited) and _inside(p,panel) for p in points)):
            # Validate against the ORIGINAL line before padding. The clickable
            # region changes, never the boundary axis, width or source description.
            padded=_bounds([cited[:2],cited[2:]],page)
            return SourceRef(kind="image",page=page.number,bbox=padded),True
        if (region.page==page.number and max(cited[0],panel[0])<min(cited[2],panel[2])
                and max(cited[1],panel[1])<min(cited[3],panel[3])):
            return SourceRef(kind="image",page=page.number,bbox=region.bbox),True
    elif points and all(_point(p) and _inside(p,floor.source.bbox) for p in points):
        box=_bounds(points,page)
        box=[max(box[0],floor.source.bbox[0]),max(box[1],floor.source.bbox[1]),min(box[2],floor.source.bbox[2]),min(box[3],floor.source.bbox[3])]
        if box[0]<box[2] and box[1]<box[3]:
            return SourceRef(kind="image",page=page.number,bbox=box),True
    return SourceRef(kind="image",page=page.number,bbox=floor.source.bbox),False


def _feature_type(kind):
    if kind=="stairs":
        return "IfcStairFlight","stairs"
    if kind in {"sink","toilet","shower","bath"}:
        return "IfcSanitaryTerminal","fixture"
    if kind=="appliance":
        return "IfcBuildingElementProxy","fixture"
    if kind in {"table","chair","cabinet","bed","sofa"}:
        return "IfcFurnishingElement","furniture"
    return "IfcBuildingElementProxy","other"


def _generate_floor(builder,floor,storey,page,matrix,known,prefix,warnings):
    unit="m" if known else "relative"
    wall_height,default_width,plate=(2.6,.12,.04) if known else (1.2,.08,.02)
    spaces,physical=[],[]

    def add(ifc_type,key,label,kind,semantic,source,polygon=None,z=0,height=0,assumptions=None,basis="observed",note="",reason="",environment="unknown",schematic=False):
        status="unresolved" if reason else "schematic" if schematic else "reconstructed"
        full_note=" ".join(text for text in (note,reason) if text)
        entity=builder.product(ifc_type,key,label,polygon,z,height,storey,source,assumptions or [],basis,full_note,kind,
                               representation=status,semantic_type=semantic,environment=environment)
        (spaces if ifc_type=="IfcSpace" else physical).append(entity)
        return entity

    room_polygons={i:_valid_polygon(r.polygon,floor.source.bbox) for i,r in enumerate(floor.rooms,start=1)}
    conflicts=set()
    for i,a in room_polygons.items():
        for j,b in room_polygons.items():
            if i<j and a is not None and b is not None and a.intersection(b).area>1e-12:
                conflicts.update((i,j))
    for i,room in enumerate(floor.rooms,start=1):
        source,localized=_item_source(None,room.polygon,floor,page)
        shape=room_polygons[i]
        reason="Invalid room footprint." if shape is None else "Conflicting room interiors overlap." if i in conflicts else ""
        if not localized:
            reason+=" Unlocalized: coarse floor source region only."
        world=None if reason else [_transform(matrix,p) for p in list(shape.exterior.coords)[:-1]]
        add("IfcSpace",f"{prefix}:room:{i}",room.label,"outdoor" if room.environment=="outdoor" else "room", "space",source,
            world,-plate,plate,[_assumption("floor_plate_thickness",plate,unit,"Display-only footprint plate; not a measured slab.")],
            room.basis,room.note,reason,room.environment)

    # Validate complete boundary inventory before choosing hosts, never first-match keys.
    key_counts=Counter(b.key for b in floor.boundaries)
    boundary_records={}
    for i,boundary in enumerate(floor.boundaries,start=1):
        source,localized=_item_source(boundary.source,boundary.segment,floor,page)
        expected_length=len(boundary.segment)>=2 if boundary.kind=="open_edge" else len(boundary.segment)==2
        valid=(localized and expected_length and all(_point(p) and _inside(p,source.bbox) and _inside(p,floor.source.bbox) for p in boundary.segment))
        if valid:
            edges=[tuple(sorted((tuple(a),tuple(b)))) for a,b in zip(boundary.segment,boundary.segment[1:])]
            valid=all(a!=b for a,b in edges) and len(set(edges))==len(edges)
        reason="" if valid else "Invalid boundary geometry or source association."
        if not localized:
            reason+=" Unlocalized: coarse floor source region only."
        if not boundary.key.strip() or key_counts[boundary.key]>1:
            reason="Duplicate or missing boundary key; host identity is ambiguous. "+reason
        padding_note=("Source selection region padded by one original-page pixel on each available side of its zero-width/height axis; not measured boundary thickness."
                      if localized and source.bbox!=boundary.source.bbox else "")
        boundary_records[i]={"description":boundary,"source":source,"reason":reason,"alias":None,"padding_note":padding_note}
    # Exact equivalent segments can share one mesh; uncertain collinear overlaps cannot.
    for i,record in boundary_records.items():
        if record["reason"]:
            continue
        boundary=record["description"]
        for j,other in boundary_records.items():
            if i>=j or other["reason"]:
                continue
            target=other["description"]
            if LineString(boundary.segment).intersection(LineString(target.segment)).length<=0:
                continue
            equivalent=(boundary.kind==target.kind and (boundary.segment==target.segment or boundary.segment==list(reversed(target.segment)))
                        and boundary.thickness_segment==target.thickness_segment)
            if equivalent:
                # Exact duplicates have identical physical geometry; smallest key is stable.
                primary,alias=(i,j) if boundary.key<target.key else (j,i)
                boundary_records[alias]["alias"]=primary
            else:
                record.setdefault("overlap",True)
                other.setdefault("overlap",True)
    for record in boundary_records.values():
        if record.get("overlap"):
            record["reason"]="Ambiguous overlapping boundary descriptions."
    hosts={}
    generated={}
    for i,record in boundary_records.items():
        boundary=record["description"]
        source=record["source"]
        reason=record["reason"]
        alias=record["alias"]
        if alias:
            reason="Exact duplicate boundary; one shared mesh is represented by boundary "+boundary_records[alias]["description"].key+"."
        world=None
        width=default_width
        low,high=-width/2,width/2
        assumptions=[]
        if not reason:
            segment_points=[_transform(matrix,p) for p in boundary.segment]
            a,b=segment_points[:2]
            observed_band=_depicted_band(boundary,floor,page,matrix)
            observed_width=observed_band is not None
            if observed_width:
                low,high=observed_band
                width=high-low
                if boundary.kind!="wall":
                    low,high=-width/2,width/2
            if not observed_width:
                assumptions.append(_assumption("thickness",width,unit,"Display boundary width; no usable depicted thickness segment."))
            if boundary.kind=="wall":
                assumptions.append(_assumption("normal_offsets",f"{low:.12g}, {high:.12g}",unit,
                    "Wall band follows the supplied cross-wall face positions; its reference line is not assumed to be a centerline. This is image-derived placement, not a field measurement."
                    if observed_width else "Wall band is centered on the supplied reference line using the explicitly assumed display width."))
            height=wall_height if boundary.kind=="wall" else (.9 if known else .35) if boundary.kind=="railing" else plate
            if boundary.kind=="open_edge":
                width=plate
                low,high=-width/2,width/2
                assumptions=[_assumption("marker_width",width,unit,"Flat display marker for an open edge; not a physical wall.")]
            assumptions.append(_assumption("height",height,unit,"Display extrusion only; no source height established."))
            world=_band(a,b,low,high)
        else:
            height=0
        ifc_type={"wall":"IfcWall","railing":"IfcRailing","open_edge":"IfcBuildingElementProxy"}[boundary.kind]
        entity=add(ifc_type,f"{prefix}:boundary:{i}",boundary.label,boundary.kind,boundary.kind,source,world,0,height,
                   assumptions,boundary.basis," ".join(filter(None,[boundary.note,record["padding_note"]])),reason,schematic=boundary.kind!="wall")
        if not reason and boundary.kind=="open_edge" and len(segment_points)>2:
            shape=entity.Representation.Representations[0]
            shape.Items=list(shape.Items)+[builder.solid_item(_rectangle(a,b,width),0,height)
                for a,b in zip(segment_points[1:],segment_points[2:])]
        generated[i]=(entity,low,high)
        if boundary.kind=="wall" and not reason:
            hosts[boundary.key]=(entity,boundary.segment,low,high)
    for i,record in boundary_records.items():
        if record["alias"] and not record["reason"]:
            primary=record["alias"]
            seen=set()
            while boundary_records[primary]["alias"] and primary not in seen:
                seen.add(primary);primary=boundary_records[primary]["alias"]
            target=boundary_records[primary]
            if not target["reason"] and target["description"].kind=="wall":
                entity,low,high=generated[primary]
                hosts[record["description"].key]=(entity,target["description"].segment,low,high)

    # Check all opening intervals before cutting any wall; conflicts have no arbitrary winner.
    opening_records={}
    for i,opening in enumerate(floor.openings,start=1):
        source,localized=_item_source(opening.source,opening.segment,floor,page)
        host=hosts.get(opening.host_wall)
        reason="" if host else "Missing, unresolved or non-wall host boundary."
        if not localized:
            reason="Invalid opening source association. Unlocalized: coarse floor source region only."
        elif len(opening.segment)!=2 or not all(_point(p) and _inside(p,source.bbox) and _inside(p,floor.source.bbox) for p in opening.segment):
            reason="Opening segment is outside its original source region or invalid."
        projected=[];interval=[]
        if not reason:
            wall,segment,low,high=host
            aspect=page.width/page.height
            plane=lambda p:[aspect*p[0],-p[1]]
            a,b=[plane(p) for p in segment]
            dx,dy=b[0]-a[0],b[1]-a[1]
            length2=dx*dx+dy*dy
            length=math.sqrt(length2)
            factor=math.hypot(matrix[0][1],matrix[1][1])
            for point in opening.segment:
                p=plane(point)
                t=((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2
                original=[segment[0][k]+t*(segment[1][k]-segment[0][k]) for k in (0,1)]
                nearest=_transform(matrix,original)
                offset=((p[0]-a[0])*(-dy)+(p[1]-a[1])*dx)/length*factor
                # Numeric tolerance only: source-line contacts must survive display rotation.
                tolerance=1e-12*max(1,abs(low),abs(high),length*factor)
                if (not 0<=t<=1 or not low-tolerance<=offset<=high+tolerance
                    or not (source.bbox[0]-1e-9<=original[0]<=source.bbox[2]+1e-9 and source.bbox[1]-1e-9<=original[1]<=source.bbox[3]+1e-9)
                    or not _inside(original,floor.source.bbox)):
                    break
                projected.append(nearest);interval.append(t)
            if len(projected)!=2 or math.dist(*projected)==0:
                reason="Opening cannot be projected within its explicit host band and original source region."
        opening_records[i]={"description":opening,"source":source,"host":host,"reason":reason,"points":projected,"interval":sorted(interval)}
    for i,record in opening_records.items():
        if record["reason"]:continue
        for j,other in opening_records.items():
            if i<j and not other["reason"] and record["host"][0].GlobalId==other["host"][0].GlobalId:
                if min(record["interval"][1],other["interval"][1])-max(record["interval"][0],other["interval"][0])>1e-12:
                    record["conflict"]=other["conflict"]=True
    for i,record in opening_records.items():
        opening=record["description"]
        reason="Conflicting overlapping opening spans on the same host." if record.get("conflict") else record["reason"]
        key=f"{prefix}:opening:{i}"
        assumptions=[];world=None;sill=height=0
        if not reason:
            wall,_,low,high=record["host"]
            width=high-low
            a,b=record["points"]
            length=math.dist(a,b)
            normal=[-(b[1]-a[1])/length,(b[0]-a[0])/length]
            # Gap endpoints may be listed in either order; band signs use the host's direction.
            host_segment=record["host"][1]
            host_a,host_b=[_transform(matrix,p) for p in host_segment]
            if sum((b[i]-a[i])*(host_b[i]-host_a[i]) for i in (0,1))<0:
                normal=[-value for value in normal]
            center=(low+high)/2
            a,b=[[point[i]+normal[i]*center for i in (0,1)] for point in (a,b)]
            sill,height=((0,2.1) if opening.kind=="door" else (1,1.2)) if known else ((0,.8) if opening.kind=="door" else (.4,.45))
            void=builder.model.create_entity("IfcOpeningElement",GlobalId=builder.guid(key+":void"),Name="Display opening",
                ObjectPlacement=builder.placement,Representation=builder.solid(_rectangle(a,b,width*1.4),sill,height),PredefinedType="OPENING")
            builder.model.create_entity("IfcRelVoidsElement",GlobalId=builder.guid(key+":void-relation"),RelatingBuildingElement=wall,RelatedOpeningElement=void)
            world=_rectangle(a,b,min(.03,width/2))
            assumptions=[_assumption("height",height,unit,"Display opening height, not a measured source value."),
                _assumption("sill_height",sill,unit,"Display sill height, not a measured source value."),
                _assumption("thickness",min(.03,width/2),unit,"Display fill thickness."),
                _assumption("cross_wall_center",center,unit,"Void and fill are centered between the host's supplied face positions or explicitly assumed display faces; longitudinal source-gap endpoints are unchanged."),
                _assumption("host_projection","Within rendered host wall band",None,"Source segment projected only onto its explicitly named wall; original source region unchanged.")]
        entity=add("IfcDoor" if opening.kind=="door" else "IfcWindow",key,opening.label,opening.kind,opening.kind,record["source"],world,sill,height,
                   assumptions,opening.basis,opening.note,reason)
        if not reason:
            builder.model.create_entity("IfcRelFillsElement",GlobalId=builder.guid(key+":fill-relation"),RelatingOpeningElement=void,RelatedBuildingElement=entity)

    for i,feature in enumerate(floor.features,start=1):
        source,localized=_item_source(feature.source,feature.polygon,floor,page)
        fallback=(localized and not feature.polygon and _inside(source.bbox[:2],floor.source.bbox)
                  and _inside(source.bbox[2:],floor.source.bbox))
        points=feature.polygon
        if fallback:
            left,top,right,bottom=source.bbox
            points=[[left,top],[right,top],[right,bottom],[left,bottom]]
        shape=_valid_polygon(points,source.bbox) if localized and all(_point(p) and _inside(p,floor.source.bbox) for p in points) else None
        reason="" if shape is not None else "Invalid feature footprint; source item retained without invented geometry."
        if not localized:reason+=" Unlocalized: coarse floor source region only."
        world=[_transform(matrix,p) for p in list(shape.exterior.coords)[:-1]] if shape is not None else None
        ifc_type,kind=_feature_type(feature.kind)
        assumptions=[_assumption("schematic_thickness",plate,unit,"Flat feature symbol; vertical dimensions, stair rise and step counts are not established.")]
        if fallback:
            assumptions.append(_assumption("footprint","Source bounding box",None,"No feature polygon was supplied; the original evidence box is an approximate display footprint, not a traced object boundary."))
        if feature.kind=="stairs" and world:
            assumptions.append(_assumption("stair_symbol","Level parallel marks",None,"Symbol marks, not a source step count or rise. No stair travel direction is inferred; mark orientation follows the display footprint only."))
            assumptions.append(_assumption("symbol_mark_thickness",plate/4,unit,"Display relief for level schematic marks; not a riser dimension."))
        entity=add(ifc_type,f"{prefix}:feature:{i}",feature.label,kind,feature.kind,source,world,plate,plate,assumptions,
            feature.basis,feature.note,reason,schematic=True)
        if feature.kind=="stairs" and world:
            builder.stair_symbol(entity,world,plate*2,plate/4)
    for i,item in enumerate(floor.unresolved,start=1):
        source,localized=_item_source(item.source,[],floor,page)
        reason=item.reason or "Source feature unresolved."
        if not localized:reason+=" Unlocalized: coarse floor source region only."
        add("IfcBuildingElementProxy",f"{prefix}:unresolved:{i}",item.label,"other",item.category,source,reason=reason)
    if spaces:builder.aggregate(storey,spaces,prefix+":spaces")
    if physical:
        builder.model.create_entity("IfcRelContainedInSpatialStructure",GlobalId=builder.guid(prefix+":containment"),RelatedElements=physical,RelatingStructure=storey)
    unresolved=sum(e.representation=="unresolved" for e in builder.elements if e.storey_id==storey.GlobalId)
    if unresolved:warnings.append(f"{floor.label}: {unresolved} source items remain individually inspectable as unresolved; no geometry was invented for them.")


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
            floor_assumptions.append(_assumption("page_extent",10,"relative","The full source page's longest extent is 10 display units, preserving drawn proportions across its floor diagrams. This does not prove equal physical scale; differently scaled diagrams or separate pages remain schematic, not metric comparisons."))
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
        _generate_floor(builder,floor,storey,page,matrix,known,prefix,warnings)
    if not builder.elements:
        raise DocumentError("No depicted feature entries were supplied; no model or inventory was saved.",422)
    if not any(e.Representation for e in builder.products):
        warnings.append("No 3D geometry is available: this artifact preserves only unresolved source inventory.")
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
    manifest = ArtifactManifest(artifact_id=artifact_id,source_filename=document.filename,pages=embedded,scene=scene,description=description)
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
