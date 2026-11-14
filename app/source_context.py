"""Only source properties enter answering. Inferred geometry is never evidence."""
import json
from collections import Counter

IFC_CONTEXT_PROPERTIES = 12


def source_context(document):
    scene = document.scene
    if not scene:
        return ""
    if document.kind == "ifc" and not scene.derived:
        # Every ID/class is included; properties are an explicitly bounded view.
        records = []
        omitted = 0
        for e in scene.elements:
            props = e.properties[:IFC_CONTEXT_PROPERTIES]
            omitted += len(e.properties) - len(props)
            records.append({"element_id": e.id, "ifc_type": e.ifc_type, "kind": e.kind,
                            "name": e.name, "storey_id": e.storey_id,
                            "source_step_id": e.source.step_id,
                            "properties": [p.model_dump() for p in props],
                            "omitted_properties": max(0, len(e.properties) - len(props))})
        context = {"source": "Extracted records from the uploaded IFC; not a claim about the as-built building",
                   "catalog_complete": scene.catalog_complete,
                   "counts_by_kind": dict(Counter(e.kind for e in scene.elements)),
                   "property_view": "At most 12 properties per element; other properties may exist in the IFC/inspector. Missing here does not establish absence from the original file.",
                   "omitted_properties": omitted, "warnings": scene.warnings, "elements": records}
        return json.dumps(context, ensure_ascii=False)
    # This is only a candidate association index. NO sizes/heights/properties/assumptions.
    return json.dumps({"association_index_only": "These are fallible image interpretations, NOT new source evidence. Answer from original pages. Use an ID only if its room label/region actually supports the answer; otherwise leave highlight_ids empty.",
                       "floors": [{"id":f.id,"label":f.label,"page":f.source.page,"bbox":f.source.bbox}
                                  for f in scene.floors],
                       "objects": [{"id": e.id, "kind": e.kind, "name": e.name,
                                    "page": e.source.page, "bbox": e.source.bbox, "floor_id":e.storey_id}
                                   for e in scene.elements if e.geometry is not None and e.representation != "unresolved"]}, ensure_ascii=False)
