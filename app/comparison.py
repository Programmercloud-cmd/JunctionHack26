"""Source-coordinate comparison derived from the reopened IFC meshes, not descriptions."""
import math
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union
from .scene import PlanComparison


def inverse_transform(matrix):
    if len(matrix)!=3 or any(len(row)!=3 for row in matrix) or not all(math.isfinite(v) for row in matrix for v in row):
        raise ValueError('Invalid source transform')
    a,b,c=matrix[0]; d,e,f=matrix[1]
    determinant=a*e-b*d
    if determinant==0 or matrix[2]!=[0,0,1]:
        raise ValueError('Noninvertible source transform')
    return lambda p: [(e*(p[0]-c)-b*(p[1]-f))/determinant,(-d*(p[0]-c)+a*(p[1]-f))/determinant]


def _triangles(geometry):
    points=[geometry.positions[i:i+3] for i in range(0,len(geometry.positions),3)]
    for i in range(0,len(geometry.indices),3):
        yield [points[j] for j in geometry.indices[i:i+3]]


def _section(geometry,height,inverse):
    lines=[]
    for triangle in _triangles(geometry):
        intersections=set()
        for start,end in zip(triangle,triangle[1:]+triangle[:1]):
            if start[2]==height:
                intersections.add(tuple(round(v,12) for v in inverse(start)))
            if (start[2]<height<end[2]) or (end[2]<height<start[2]):
                t=(height-start[2])/(end[2]-start[2])
                point=[start[k]+t*(end[k]-start[k]) for k in range(2)]
                intersections.add(tuple(round(v,12) for v in inverse(point)))
        if len(intersections)==2:
            lines.append(LineString(list(intersections)))
    # Rounding joins the same tessellation intersection reached from adjacent faces;
    # it does not snap the model to a drawing feature or repair intended geometry.
    return unary_union(list(polygonize(unary_union(lines)))) if lines else Polygon()


def _projection(geometry,inverse):
    triangles=[]
    for triangle in _triangles(geometry):
        poly=Polygon([inverse(p) for p in triangle])
        if poly.is_valid and poly.area>0:
            triangles.append(poly)
    return unary_union(triangles) if triangles else Polygon()


def _rings(shape):
    if shape.is_empty:
        return []
    if shape.geom_type=='Polygon':
        return [[list(p) for p in shape.exterior.coords]]+[[list(p) for p in ring.coords] for ring in shape.interiors]
    return [ring for part in getattr(shape,'geoms',[]) for ring in _rings(part)]


def build_comparison(scene):
    if not scene.derived:
        return []
    floors={f.id:f for f in scene.floors}
    inverses={}
    for floor in scene.floors:
        source_inverse = inverse_transform(floor.transform)
        placement_inverse = inverse_transform(floor.building_transform)
        inverses[floor.id] = lambda p,s=source_inverse,b=placement_inverse:s(b(p))
    result=[]
    for element in scene.elements:
        floor=floors[element.storey_id]
        entry=PlanComparison(element_id=element.id,floor_id=floor.id,page=floor.source.page,
                             layer='unresolved',method='Unresolved source region; no reconstructed footprint')
        geometry=element.geometry
        if element.representation=='unresolved' or geometry is None:
            result.append(entry)
            continue
        if geometry.type!='mesh':
            raise ValueError('Derived comparison requires actual tessellated IFC geometry')
        inverse=inverses[floor.id]
        if element.kind=='wall':
            zs=geometry.positions[2::3]
            entry.cut_height=(min(zs)+max(zs))/2
            entry.layer='walls'
            entry.method='Actual IFC horizontal section at an assumed display height; not a measured elevation'
            shape=_section(geometry,entry.cut_height,inverse)
        else:
            entry.layer=('spaces' if element.kind in {'room','outdoor'} else
                         'openings' if element.kind in {'door','window'} else 'features')
            entry.method='Actual IFC mesh footprint projection into the original page'
            shape=_projection(geometry,inverse)
        entry.polygons=_rings(shape)
        # Empty cuts are reported rather than replaced by a source bbox masquerading as geometry.
        if not entry.polygons:
            entry.method+='; no polygon at this section/projection'
        result.append(entry)
    return result
