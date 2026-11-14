"""Conservative source-based associations. Never match by inferred geometry."""
import re


def iou(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - overlap
    return overlap / union if union else 0


def validated_highlights(draft, document):
    scene = document.scene
    if not scene or draft.status != "answered":
        return []
    elements = {e.id: e for e in scene.elements}
    if document.kind == "ifc" and not scene.derived:
        backed = {e.element_id for e in draft.model_evidence}
        return list(dict.fromkeys(x for x in draft.highlight_ids if x in elements and x in backed))
    accepted = []
    for evidence in draft.evidence:
        box = evidence.bbox
        if (box[2]-box[0])*(box[3]-box[1]) >= .8:
            continue
        text = " ".join(re.findall(r"\w+", (evidence.label + " " + evidence.observation).casefold()))
        matches = []
        for element in scene.elements:
            if (element.geometry is None or element.representation == "unresolved"
                    or element.source.page != evidence.page or iou(element.source.bbox, box) < .5):
                continue
            name = " ".join(re.findall(r"\w+", element.name.casefold()))
            if name and f" {name} " in f" {text} ":
                matches.append(element)
        # Different semantic records can share a source region (e.g. terrace and
        # open edge). Exact cited source names may distinguish them, but duplicate
        # named objects remain ambiguous even if the model requests only one ID.
        if len(matches) == 1 and matches[0].id in draft.highlight_ids:
            accepted.append(matches[0].id)
    return list(dict.fromkeys(accepted))


def whole_model_count_kind(question):
    """Only unqualified, explicitly scoped counts. No fuzzy qualifier stripping."""
    match = re.fullmatch(r"how many (windows|doors|walls|rooms|spaces) (?:are |are there )?(?:in|does) (?:this|the|the uploaded) (?:ifc )?model(?: have)?\??", question.strip().lower())
    return {"windows": "window", "doors": "door", "walls": "wall", "rooms": "room", "spaces": "room"}.get(match[1]) if match else None
