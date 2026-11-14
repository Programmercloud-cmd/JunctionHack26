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

from .artifact_schema import ARTIFACT_MARKER, DISPLAY_UNIT, MANIFEST_PROPERTY, PSET_NAME, ArtifactManifest, EmbeddedPage, EmbeddedSource
from .building import BoundaryRegion, BuildingDescription
from .documents import Document, DocumentError
from .ifc_import import MAX_ELEMENTS, MAX_IFC_BYTES, MAX_TRIANGLES, GLOBAL_ID
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
        return key if GLOBAL_ID.fullmatch(key) else ifcopenshell.guid.compress(uuid.uuid5(self.namespace,key).hex)

    def point(self, coordinates):
        return self.model.create_entity("IfcCartesianPoint",Coordinates=[float(v) for v in coordinates])

    def aggregate(self, parent, children, key):
        self.model.create_entity("IfcRelAggregates",GlobalId=self.guid("aggregate:"+key),RelatingObject=parent,RelatedObjects=children)

    def pset(self, entity, name, values, key):
        props = [self.model.create_entity("IfcPropertySingleValue",Name=k,NominalValue=self.model.create_entity("IfcText",v)) for k,v in values.items()]
        pset = self.model.create_entity("IfcPropertySet",GlobalId=self.guid("pset:"+key),Name=name,HasProperties=props)
        self.model.create_entity("IfcRelDefinesByProperties",GlobalId=self.guid("property:"+key),RelatedObjects=[entity],RelatingPropertyDefinition=pset)

    def solid_item(self, points, z, height, holes=None):
        curve = self.model.create_entity("IfcPolyline",Points=[self.point(p) for p in points+[points[0]]])
        if holes:
            inner=[self.model.create_entity("IfcPolyline",Points=[self.point(p) for p in ring+[ring[0]]]) for ring in holes]
            profile=self.model.create_entity("IfcArbitraryProfileDefWithVoids",ProfileType="AREA",OuterCurve=curve,InnerCurves=inner)
        else:
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

    def feature_symbol(self, entity, points, kind, z, height):
        """Display motifs clipped to the supplied footprint; never inferred construction."""
        footprint=Polygon(points)
        left,bottom,right,top=footprint.bounds
        items=[]

        def append(shape,base,depth):
            pieces=[shape] if shape.geom_type=="Polygon" else list(getattr(shape,"geoms",[]))
            for piece in pieces:
                if piece.geom_type=="Polygon" and piece.area>0:
                    exterior=[list(p) for p in list(piece.exterior.coords)[:-1]]
                    holes=[[list(p) for p in list(ring.coords)[:-1]] for ring in piece.interiors]
                    items.append(self.solid_item(exterior,base,depth,holes))

        if kind in {"table","chair"}:
            append(footprint,z+height*.85,height*.15)
            width=(right-left)*.12
            # Symmetric display supports, without chair-facing or source leg-count claims.
            for strip in (box(left,bottom,left+width,top),box(right-width,bottom,right,top)):
                append(footprint.intersection(strip),z,height*.85)
        elif kind in {"sink","toilet","shower","bath"}:
            append(footprint,z,height*.35)
            inset=footprint.buffer(-min(right-left,top-bottom)*.12,join_style=2)
            append(footprint.difference(inset),z+height*.35,height*.65)
        elif kind=="stairs":
            append(footprint,z,height*.9)
        else:
            append(footprint,z,height)
        entity.Representation.Representations[0].Items=items
        if kind=="stairs":
            self.stair_symbol(entity,points,z+height*.9,height*.1)

    def connected_stair(self, entity, points, z, rise, thickness):
        """Continuous schematic flight within the supplied footprint, no tread facts."""
        outline=Polygon(points)
        rectangle=list(outline.minimum_rotated_rectangle.exterior.coords)[:4]
        a,b=max(zip(rectangle,rectangle[1:]+rectangle[:1]),key=lambda pair:math.dist(*pair))
        length=math.dist(a,b);axis=[(b[k]-a[k])/length for k in (0,1)]
        distances=[sum(p[k]*axis[k] for k in (0,1)) for p in points]
        low,high=min(distances),max(distances)
        lower=[[p[0],p[1],z+rise*(distance-low)/(high-low)-thickness] for p,distance in zip(points,distances)]
        upper=[[p[0],p[1],p[2]+thickness] for p in lower]
        faces=[]
        for vertices in [list(reversed(lower)),upper]+[[lower[i],lower[(i+1)%len(points)],upper[(i+1)%len(points)],upper[i]] for i in range(len(points))]:
            loop=self.model.create_entity('IfcPolyLoop',Polygon=[self.point(p) for p in vertices])
            bound=self.model.create_entity('IfcFaceOuterBound',Bound=loop,Orientation=True)
            faces.append(self.model.create_entity('IfcFace',Bounds=[bound]))
        shell=self.model.create_entity('IfcClosedShell',CfsFaces=faces)
        solid=self.model.create_entity('IfcFacetedBrep',Outer=shell)
        shape=self.model.create_entity('IfcShapeRepresentation',ContextOfItems=self.context,RepresentationIdentifier='Body',RepresentationType='Brep',Items=[solid])
        entity.Representation=self.model.create_entity('IfcProductDefinitionShape',Representations=[shape])

    def product(self, ifc_type, key, name, polygon, z, height, storey, source, assumptions, basis="observed", note="", kind=None,
                representation="reconstructed", semantic_type="", environment="unknown"):
        if len(self.elements) >= MAX_ELEMENTS:
            raise DocumentError(f"Generated IFC exceeds the {MAX_ELEMENTS:,}-element limit; no inventory was truncated.",413)
        entity = self.model.create_entity(ifc_type,GlobalId=self.guid(key),Name=name,ObjectPlacement=storey.ObjectPlacement,
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



def _feature_polygon(points, source_box, floor_box, page):
    """Accept only subpixel own-citation rounding; all other geometry guards stay strict."""
    suffix=" Source item retained without invented geometry."
    if len(points)<3 or not all(_point(p) for p in points):
        return None,"Invalid feature footprint coordinates or fewer than three vertices."+suffix,False
    if not all(_inside(p,floor_box) for p in points):
        return None,"Feature footprint is outside its floor source region."+suffix,False
    shape=_valid_polygon(points,floor_box)
    if shape is None:
        return None,"Feature footprint is self-intersecting or has no positive area."+suffix,False
    if all(_inside(p,source_box) for p in points):
        return shape,"",False
    dimensions=[getattr(page,"width",None),getattr(page,"height",None)]
    if not all(type(dimension) is int and dimension>0 for dimension in dimensions):
        return None,"Feature footprint is outside its source region; saved raster dimensions are unavailable."+suffix,False
    # These are the saved citation raster dimensions, never provider/viewer image
    # sizes or physical units. Do not move the polygon or expand its source box.
    dx,dy=(.5/dimension for dimension in dimensions)
    left,top,right,bottom=source_box
    if all(left-dx<=p[0]<=right+dx and top-dy<=p[1]<=bottom+dy for p in points):
        return shape,"",True
    return None,"Feature footprint extends beyond its source region by more than half a saved source-page pixel."+suffix,False


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


def _generate_floor(builder,floor,storey,page,matrix,known,prefix,warnings,wall_height=None,connections=None):
    unit="m" if known else "relative"
    default_height,default_width,plate=(2.6,.12,.04) if known else (1.2,.08,.02)
    wall_height=wall_height or default_height
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
        source,localized=_item_source(room.source,room.polygon,floor,page)
        shape=room_polygons[i]
        reason="Invalid room footprint." if shape is None else "Conflicting room interiors overlap." if i in conflicts else ""
        if not localized:
            reason+=" Unlocalized: coarse floor source region only."
        world=None if reason else [_transform(matrix,p) for p in list(shape.exterior.coords)[:-1]]
        add("IfcSpace",room.persistent_id or f"{prefix}:room:{i}",room.label,"outdoor" if room.environment=="outdoor" else "room", "space",source,
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
        footprint = _valid_polygon(boundary.footprint,source.bbox) if boundary.footprint else None
        if boundary.footprint and (boundary.kind!='wall' or footprint is None or not all(_inside(p,floor.source.bbox) for p in boundary.footprint)):
            reason="Invalid supplied wall footprint; source retained without replacement geometry."
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
                        and boundary.thickness_segment==target.thickness_segment and boundary.footprint==target.footprint)
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
            if boundary.footprint:
                world=[_transform(matrix,p) for p in boundary.footprint]
                length=math.dist(a,b);normal=[-(b[1]-a[1])/length,(b[0]-a[0])/length]
                offsets=[sum((p[k]-a[k])*normal[k] for k in (0,1)) for p in world]
                low,high=min(offsets),max(offsets)
                assumptions=[item for item in assumptions if item.property not in {'thickness','normal_offsets'}]
                assumptions.append(_assumption('footprint','Explicit source polygon',None,'Tapered/angled physical wall footprint extruded exactly as supplied; vertical height remains separately attributed.'))
        else:
            height=0
        ifc_type={"wall":"IfcWall","railing":"IfcRailing","open_edge":"IfcBuildingElementProxy"}[boundary.kind]
        entity=add(ifc_type,boundary.persistent_id or f"{prefix}:boundary:{i}",boundary.label,boundary.kind,boundary.kind,source,world,0,height,
                   assumptions,boundary.basis," ".join(filter(None,[boundary.note,record["padding_note"]])),reason,schematic=boundary.kind!="wall")
        if not reason and boundary.kind=="open_edge" and len(segment_points)>2:
            shape=entity.Representation.Representations[0]
            shape.Items=list(shape.Items)+[builder.solid_item(_rectangle(a,b,width),0,height)
                for a,b in zip(segment_points[1:],segment_points[2:])]
        generated[i]=(entity,low,high)
        if boundary.kind=="wall" and not reason:
            hosts[boundary.key]=(entity,boundary.segment,low,high,boundary.footprint)
    for i,record in boundary_records.items():
        if record["alias"] and not record["reason"]:
            primary=record["alias"]
            seen=set()
            while boundary_records[primary]["alias"] and primary not in seen:
                seen.add(primary);primary=boundary_records[primary]["alias"]
            target=boundary_records[primary]
            if not target["reason"] and target["description"].kind=="wall":
                entity,low,high=generated[primary]
                hosts[record["description"].key]=(entity,target["description"].segment,low,high,target["description"].footprint)

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
            wall,segment,low,high,footprint=host
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
                if footprint and (not Polygon(footprint).buffer(1e-12).covers(LineString([point,original]))):
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
        key=opening.persistent_id or f"{prefix}:opening:{i}"
        assumptions=[];world=None;sill=height=0
        if not reason:
            wall,_,low,high,_=record["host"]
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
            sill*=wall_height/default_height; height*=wall_height/default_height
            void=builder.model.create_entity("IfcOpeningElement",GlobalId=builder.guid(key+":void"),Name="Display opening",
                ObjectPlacement=storey.ObjectPlacement,Representation=builder.solid(_rectangle(a,b,width*1.4),sill,height),PredefinedType="OPENING")
            builder.model.create_entity("IfcRelVoidsElement",GlobalId=builder.guid(key+":void-relation"),RelatingBuildingElement=wall,RelatedOpeningElement=void)
            world=_rectangle(a,b,min(.03,width/2))
            assumptions=[_assumption("height",height,unit,"Display opening height, not a measured source value."),
                _assumption("sill_height",sill,unit,"Display sill height, not a measured source value."),
                _assumption("thickness",min(.03,width/2),unit,"Display fill thickness."),
                _assumption("cross_wall_center",center,unit,"Void and fill are centered between the host's supplied face positions or explicitly assumed display faces; longitudinal source-gap endpoints are unchanged."),
                _assumption("host_projection","Within rendered host wall band",None,"Source segment projected only onto its explicitly named wall; original source region unchanged.")]
        padding_note=(" Original line citation preserved; selection region padded by one source pixel, not measured opening width."
                      if record["source"].bbox!=opening.source.bbox and (opening.source.bbox[0]==opening.source.bbox[2] or opening.source.bbox[1]==opening.source.bbox[3]) else "")
        entity=add("IfcDoor" if opening.kind=="door" else "IfcWindow",key,opening.label,opening.kind,opening.kind,record["source"],world,sill,height,
                   assumptions,opening.basis,opening.note+padding_note,reason)
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
        if localized:
            shape,reason,rounded=_feature_polygon(points,source.bbox,floor.source.bbox,page)
        else:
            shape,reason,rounded=None,"Unlocalized feature footprint: coarse floor source region only; source item retained without invented geometry.",False
        rounding_note=(" Feature footprint extends beyond its citation by at most half a saved source-page pixel per axis; "
                       "accepted as raster-coordinate rounding. Supplied footprint and source citation are unchanged.") if rounded else ""
        world=[_transform(matrix,p) for p in list(shape.exterior.coords)[:-1]] if shape is not None else None
        ifc_type,kind=_feature_type(feature.kind)
        ratios={"table":.30,"chair":.20,"bed":.20,"sofa":.25,"cabinet":.50,"appliance":.40,
                "sink":.25,"toilet":.25,"shower":.10,"bath":.10,"stairs":.10,"other":.10}
        ratio=ratios[feature.kind]
        height=wall_height*ratio
        motif=("Raised top with symmetric clipped supports" if feature.kind in {"table","chair"} else
               "Low body with inset rim/basin symbol" if feature.kind in {"sink","toilet","shower","bath"} else
               "Raised level footprint with parallel marks" if feature.kind=="stairs" else "Raised footprint block")
        assumptions=[_assumption("height",height,unit,f"Display height is {ratio:g} times the assumed wall height; not a source measurement or actual object height."),
            _assumption("schematic_motif",motif,None,"Display template stays inside the supplied footprint; body shape, support glyphs and basin/rim are not source construction details. Supports do not establish real leg counts; no chair facing is inferred.")]
        if fallback:
            assumptions.append(_assumption("footprint","Source bounding box",None,"No feature polygon was supplied; the original evidence box is an approximate display footprint, not a traced object boundary."))
        if feature.kind=="stairs" and world:
            assumptions.append(_assumption("stair_symbol","Level parallel marks",None,"Symbol marks, not a source step count or rise. No stair travel direction is inferred; mark orientation follows the display footprint only."))
            assumptions.append(_assumption("symbol_mark_thickness",height*.1,unit,"Display relief for level schematic marks; not a riser dimension."))
        connection=(connections or {}).get(i)
        if connection:
            assumptions.append(_assumption('connectivity',connection['target'],None,'Source-supported floor relationship. Continuous schematic flight uses attributed display rise; its slope direction is a display convention, not a source travel direction.'))
            assumptions.append(_assumption('display_rise',connection['rise'],unit,'Difference between attributed building display levels; no measured risers or stair construction details.'))
        entity=add(ifc_type,feature.persistent_id or f"{prefix}:feature:{i}",feature.label,kind,feature.kind,source,world,plate,height,assumptions,
            feature.basis,feature.note+rounding_note,reason,schematic=True)
        if world:
            if connection and connection['rise']>0:
                builder.connected_stair(entity,world,plate,connection['rise'],plate)
            else:
                builder.feature_symbol(entity,world,feature.kind,plate,height)
    for i,item in enumerate(floor.unresolved,start=1):
        source,localized=_item_source(item.source,[],floor,page)
        reason=item.reason or "Source feature unresolved."
        if not localized:reason+=" Unlocalized: coarse floor source region only."
        add("IfcBuildingElementProxy",item.persistent_id or f"{prefix}:unresolved:{i}",item.label,"other",item.category,source,reason=reason)
    if spaces:builder.aggregate(storey,spaces,prefix+":spaces")
    if physical:
        builder.model.create_entity("IfcRelContainedInSpatialStructure",GlobalId=builder.guid(prefix+":containment"),RelatedElements=physical,RelatingStructure=storey)
    unresolved=sum(e.representation=="unresolved" for e in builder.elements if e.storey_id==storey.GlobalId)
    if unresolved:warnings.append(f"{floor.label}: {unresolved} source items remain individually inspectable as unresolved; no geometry was invented for them.")


def _identity_matrix():
    return [[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]


def _floor_target(reference, floors):
    matches = [i for i,f in enumerate(floors) if reference in {f.persistent_id,f.label}]
    return matches[0] if len(matches)==1 else None


def _building_placements(description, frames, pages, warnings):
    floors=description.floors
    placements=[_identity_matrix() for _ in floors]
    supported=[False for _ in floors]
    # Same-page unscaled diagrams already share one scale. Registration adds only
    # rigid placement, never a separate scale or a modification of frozen frames.
    compatible=lambda i,j: (frames[i][1] and frames[j][1]) or (not frames[i][1] and not frames[j][1] and floors[i].source.page==floors[j].source.page and math.isclose(math.hypot(frames[i][0][0][1],frames[i][0][1][1]),math.hypot(frames[j][0][0][1],frames[j][0][1][1]),rel_tol=1e-9))
    aligned_indices=[i for i,f in enumerate(floors) if f.alignment and f.alignment.group.strip() and f.alignment.basis.strip()
        and _region(f.alignment.source,pages,f.source.page) and _point(f.alignment.anchor) and _inside(f.alignment.anchor,f.source.bbox)
        and f.rotation_degrees is not None and f.orientation_basis.strip()]
    for i in aligned_indices:
        peers=[j for j in aligned_indices if floors[j].alignment.group==floors[i].alignment.group and compatible(i,j)]
        if len(peers)>1:
            anchor=_transform(frames[i][0],floors[i].alignment.anchor)
            placements[i][0][2],placements[i][1][2]=-anchor[0],-anchor[1]
            supported[i]=True
    active=set();done=set()
    def resolve(i):
        if i in done:return True
        if i in active:return False
        reg=floors[i].registration
        if reg is None:done.add(i);return True
        active.add(i)
        j=_floor_target(reg.reference_floor_id,floors)
        valid=(reg.status=='supported' and reg.basis.strip() and j is not None and j!=i and compatible(i,j)
            and math.isfinite(reg.rotation_degrees) and _region(reg.source,pages,floors[i].source.page)
            and _region(reg.reference_source,pages,floors[j].source.page)
            and _point(reg.anchor) and _inside(reg.anchor,reg.source.bbox) and _inside(reg.anchor,floors[i].source.bbox)
            and _point(reg.reference_anchor) and _inside(reg.reference_anchor,reg.reference_source.bbox) and _inside(reg.reference_anchor,floors[j].source.bbox))
        if valid and resolve(j):
            angle=math.radians(reg.rotation_degrees)
            c,s=math.cos(angle),math.sin(angle)
            parent=placements[j]
            transform=[[parent[0][0]*c+parent[0][1]*s,-parent[0][0]*s+parent[0][1]*c,0],
                       [parent[1][0]*c+parent[1][1]*s,-parent[1][0]*s+parent[1][1]*c,0],[0,0,1]]
            anchor=_transform(transform,_transform(frames[i][0],reg.anchor))
            target=_transform(parent,_transform(frames[j][0],reg.reference_anchor))
            transform[0][2],transform[1][2]=target[0]-anchor[0],target[1]-anchor[1]
            placements[i]=transform;supported[i]=supported[j]=True
        else:
            warnings.append(f'{floors[i].label}: registration remains schematic; unsupported, conflicting, cyclic or incompatible source anchors.')
        active.remove(i);done.add(i)
        return bool(valid and supported[i])
    for i in range(len(floors)):resolve(i)
    return placements,supported


def _floor_height(floor,known,document):
    default=2.6 if known else 1.2
    value=unit=None;basis='Display assumption; source storey height unknown'
    if floor.height and floor.height.status=='observed':
        value,unit,basis=floor.height.value,floor.height.unit,'Source-referenced floor height'
    for edit in getattr(document,'user_values',[]):
        scope=edit.get('scope',{})
        if (scope.get('floor_id',edit.get('floor_id'))==floor.persistent_id
                and edit.get('property') in {'height','storey_height','display_height','floor_height'}):
            value,unit,basis=edit.get('value'),edit.get('unit'),'Provided by user; not a source-observed height'
    factors={'m':1.,'cm':.01,'mm':.001,'ft':.3048,'in':.0254}
    if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>0:
        if unit=='relative' and not known:return float(value),basis+'; relative display units',[]
        if unit in factors:
            metres=value*factors[unit]
            if known:return metres,basis,[]
            ratio=1.2/2.6
            return metres*ratio,basis+'; converted only for unscaled vertical display',[
                _assumption('vertical_display_conversion',ratio,'relative/m','Explicit display convention only. Original height and unit are preserved; horizontal plan scale remains unknown.')]
    return default,basis if value is None else 'Display assumption; supplied height unusable',[]


def _storey_placement(builder, matrix, elevation):
    axis=builder.model.create_entity('IfcAxis2Placement3D',Location=builder.point([matrix[0][2],matrix[1][2],elevation]),
        RefDirection=builder.model.create_entity('IfcDirection',DirectionRatios=[float(matrix[0][0]),float(matrix[1][0]),0.]))
    return builder.model.create_entity('IfcLocalPlacement',RelativePlacement=axis)


def _embedded_sources(document, embedded):
    sources=getattr(document,'sources',[]) or []
    source_files=getattr(document,'source_files',{}) or {}
    if not sources and document.source_bytes and document.kind=='drawing' and not document.source_bytes.lstrip().startswith(b'ISO-10303-21;'):
        identity=hashlib.sha256(document.source_bytes).hexdigest()
        sources=[{'source_id':identity,'filename':document.filename,'kind':'drawing','media_type':'application/octet-stream',
                  'pages':[{'page':p.number,'source_page':p.number} for p in embedded]}]
        source_files={identity:document.source_bytes}
    result=[]
    for source in sources:
        identity=source['source_id'];original=source_files.get(identity)
        if not original or hashlib.sha256(original).hexdigest()!=identity:
            raise DocumentError('Portable IFC is unavailable because exact original source bytes are missing; the saved local sources and interpretation remain available.',422)
        mappings=[]
        for mapping in source.get('pages',[]):
            page=next((p for p in embedded if p.number==mapping['page']),None)
            if page is None:raise DocumentError('Portable IFC source page mapping is incomplete.',422)
            page.source_id=identity;page.source_page=mapping['source_page']
            mappings.append({'page':page.number,'source_page':page.source_page,'width':page.width,'height':page.height,'sha256':page.sha256})
        result.append(EmbeddedSource(source_id=identity,filename=source['filename'],filenames=source.get('filenames',[]),
            kind=source.get('kind','drawing'),media_type=source.get('media_type','application/octet-stream'),sha256=identity,
            original_base64=base64.b64encode(original).decode('ascii'),pages=mappings,metadata=source.get('metadata',{})))
    return result


def generate_ifc(description: BuildingDescription, document: Document) -> bytes:
    description = BuildingDescription.model_validate(description)
    if any(f.view_type != "floor_plan" for f in description.floors):
        raise DocumentError("Sections, elevations, site plans and uncertain views cannot become floor geometry. Original evidence remains available.",422)
    pages = {p.number:p for p in document.pages}
    warnings = list(description.limitations)
    if not description.floors or any(not _region(f.source,pages) for f in description.floors):
        raise DocumentError("The building description needs depicted floors on available source pages.",422)
    from .identities import frame_signature
    frames = []
    for floor in description.floors:
        saved = document.frame_registry.get(floor.persistent_id)
        if saved:
            if saved["signature"] != frame_signature(floor):
                raise DocumentError("Calibration/orientation changes require an explicit source-backed transform update.",409)
            frames.append(([list(row) for row in saved["transform"]],saved["known"],saved["rotation"]))
        else:
            frames.append(_floor_frame(floor,pages[floor.source.page],warnings))
    metric = all(known for _,known,_ in frames)
    placements,supported = _building_placements(description,frames,pages,warnings)
    aligned=all(supported)
    heights=[_floor_height(floor,known,document) for floor,(_,known,_) in zip(description.floors,frames)]
    order=sorted(range(len(description.floors)),key=lambda i:(description.floors[i].order if description.floors[i].order is not None and description.floors[i].order_basis.strip() else i))
    elevations={};elevation=0.
    for i in order:
        elevations[i]=elevation;elevation+=heights[i][0]
    from .identities import artifact_namespace
    artifact_id = artifact_namespace(document)
    builder = _Builder(artifact_id,metric)
    floors = []
    for floor_index,(floor,(matrix,known,rotation)) in enumerate(zip(description.floors,frames),start=1):
        prefix = floor.persistent_id or f"floor:{floor_index}"
        page = pages[floor.source.page]
        unit = "m" if known else "relative"
        wall_height, wall_thickness, plate_thickness = (2.6,.12,.04) if known else (1.2,.08,.02)
        document.frame_registry[builder.guid(prefix)] = {"transform":[list(row) for row in matrix],
            "signature":frame_signature(floor),"known":known,"rotation":rotation,"aligned":supported[floor_index-1]}
        storey = builder.model.create_entity("IfcBuildingStorey",GlobalId=builder.guid(prefix),Name=floor.label,
            ObjectPlacement=_storey_placement(builder,placements[floor_index-1],elevations[floor_index-1]),CompositionType="ELEMENT",Elevation=elevations[floor_index-1])
        builder.aggregate(builder.building,[storey],prefix)
        floor_source = SourceRef(kind="image",page=page.number,bbox=floor.source.bbox,
            source_id=getattr(page,"source_id",None),source_page=getattr(page,"source_page",None))
        wall_height,height_basis,height_assumptions=heights[floor_index-1]
        floor_assumptions = height_assumptions+[_assumption("elevation",elevations[floor_index-1],unit,"Display stacking relative to the lowest depicted floor; absolute source elevation is unknown."),
            _assumption("reference_height",wall_height,unit,height_basis),
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
            rotation_degrees=rotation,alignment_status="supported" if supported[floor_index-1] else "schematic",observations=observations,
            assumptions=floor_assumptions,calibration=floor.calibration if known else None,
            alignment=floor.alignment if supported[floor_index-1] else None,measurements=measurements,transform=matrix,
            building_transform=placements[floor_index-1],base_elevation=elevations[floor_index-1],
            elevation_basis="Stacked display levels; absolute source elevation unknown",reference_height=wall_height,
            reference_height_basis=height_basis,registration=floor.registration.model_dump() if floor.registration else None))
        builder.pset(storey,PSET_NAME,{"Source":floor_source.model_dump_json(),"Floor":floors[-1].model_dump_json(),"ArtifactMarker":ARTIFACT_MARKER},prefix)
        connections={}
        for feature_index,feature in enumerate(floor.features,1):
            relation=feature.connection
            if feature.kind!='stairs' or relation is None:continue
            target=_floor_target(relation.target_floor_id,description.floors)
            valid=(relation.status=='supported' and relation.basis.strip() and target is not None and target!=floor_index-1
                and _region(relation.source,pages,page.number) and supported[target] and supported[floor_index-1])
            if valid and relation.target_feature_id:
                matches=[f for f in description.floors[target].features if relation.target_feature_id in {f.persistent_id,f.label} and f.kind=='stairs']
                valid=len(matches)==1
            if valid:
                connections[feature_index]={'target':description.floors[target].persistent_id or description.floors[target].label,
                    'rise':elevations[target]-elevations[floor_index-1]}
            else:
                warnings.append(f'{floor.label}: stair connection remains unresolved; unique supported target and compatible registration are required.')
        _generate_floor(builder,floor,storey,page,matrix,known,prefix,warnings,wall_height,connections)
    if not builder.elements:
        raise DocumentError("No depicted feature entries were supplied; no model or inventory was saved.",422)
    if not any(e.Representation for e in builder.products):
        warnings.append("No 3D geometry is available: this artifact preserves only unresolved source inventory.")
    warnings.extend(["Drawing-derived visualization: generated geometry and inventory are not factual building evidence.",
        "Wall heights, thicknesses, floor plates and opening vertical dimensions are display assumptions; absolute storey elevations are unknown; stacked elevations are attributed display placement."])
    if not metric:
        warnings.append("UNSCALED: at least one floor lacks calibration. Project units are relative; mixed-floor distances are not physical measurements.")
    scene = Scene(document_id=document.id,source_kind="image",units="m" if metric else "relative",elements=builder.elements,
        consistency_findings=[{'code':'unresolved_geometry','element_id':e.id,'floor_id':e.storey_id,'source':e.source.model_dump(),'message':e.note}
            for e in builder.elements if e.representation=='unresolved']+[
                {'code':'floor_relationship','source':description.floors[i].source.model_dump(),'message':warning}
                for i,f in enumerate(description.floors) for warning in warnings
                if warning.startswith(f.label+':') and ('registration remains' in warning or 'stair connection remains' in warning)],
        warnings=warnings,catalog_complete=False,derived=True,artifact_id=artifact_id,floors=floors,layout="aligned" if aligned else "schematic",
        building_id=document.building_id, revision_id=document.revision_id, parent_revision_id=document.parent_revision_id,
        revision_number=document.revision_number,review_status=document.review_status)
    if sum(((p.path.stat().st_size+2)//3)*4 for p in document.pages) > MAX_IFC_BYTES:
        raise DocumentError("Embedded source pages would exceed the existing 25 MiB IFC limit; no pages were truncated.",413)
    embedded = []
    for page in document.pages:
        data = page.path.read_bytes()
        embedded.append(EmbeddedPage(number=page.number,width=page.width,height=page.height,sha256=hashlib.sha256(data).hexdigest(),
                                     png_base64=base64.b64encode(data).decode("ascii")))
    original_sources=_embedded_sources(document,embedded)
    from .identities import expected_registry
    document.identity_registry={"version":1,"objects":expected_registry(description,artifact_id),
                                "tombstones":document.identity_registry.get("tombstones",[])}
    document.frame_registry={f.id:document.frame_registry[f.id]for f in floors}
    manifest = ArtifactManifest(artifact_id=artifact_id,source_filename=document.filename,pages=embedded,scene=scene,description=description,
        identity_registry=document.identity_registry,frame_registry=document.frame_registry,sources=original_sources,
        user_values=getattr(document,'user_values',[]),source_interpretations=getattr(document,'source_interpretations',{}),
        geometry_revision_id=getattr(document,'geometry_revision_id',None))
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
