"""Original-coordinate review images from actual reopened IFC comparison geometry."""
from PIL import ImageDraw

COLORS={"walls":(218,66,38,150),"openings":(0,133,205,180),"spaces":(25,150,55,45),"features":(132,58,188,110)}


def overlay_views(document,scene,prefix="Current"):
    from .provider import image_bytes
    result=[]
    for page in document.pages:
        with page.image()as source:
            image=source.convert("RGB")
        draw=ImageDraw.Draw(image,"RGBA")
        for entry in scene.comparison:
            if entry.page!=page.number:continue
            color=COLORS.get(entry.layer)
            if color:
                for ring in entry.polygons:
                    points=[(p[0]*image.width,p[1]*image.height)for p in ring]
                    if len(points)>=3:draw.polygon(points,fill=color,outline=color[:3]+(255,))
        for element in scene.elements:
            if element.representation!="unresolved"or element.source.page!=page.number:continue
            b=element.source.bbox
            draw.rectangle((b[0]*image.width,b[1]*image.height,b[2]*image.width,b[3]*image.height),outline=(225,140,0,255),width=2)
        result.append((f"{prefix} ACTUAL REOPENED IFC overlay on original page {page.number}. Red walls are horizontal sections; blue openings; purple feature footprints; orange unresolved regions. All section heights are display assumptions. Compare with unmodified original.",image_bytes(image)))
        image.close()
    return result


def issue_crops(document,issues):
    from .provider import image_bytes
    result=[]
    seen=set()
    for issue in issues:
        source=issue.source;key=(source.page,tuple(source.bbox))
        if key in seen or not 1<=source.page<=len(document.pages):continue
        seen.add(key);page=document.pages[source.page-1]
        with page.image()as image:
            l,t,r,b=source.bbox
            crop=image.crop((int(l*image.width),int(t*image.height),max(int(r*image.width),int(l*image.width)+1),max(int(b*image.height),int(t*image.height)+1)))
            result.append((f"Original evidence crop for issue {issue.id}, page {source.page}, ORIGINAL page bbox {source.bbox}; output coordinates must remain original-page coordinates.",image_bytes(crop)))
            crop.close()
    return result
