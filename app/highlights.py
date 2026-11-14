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
                    or element.source.page != evidence.page):
                continue
            source=element.source.bbox
            contained=(source[0]<=box[0] and source[1]<=box[1] and source[2]>=box[2] and source[3]>=box[3])
            overlaps=iou(source,box)>=.5
            if not (overlaps or contained):continue
            name = " ".join(re.findall(r"\w+", element.name.casefold()))
            if name and f" {name} " in f" {text} ":
                matches.append((element,overlaps or (contained and element.kind in {"room","outdoor"})))
        # Different semantic records can share a source region (e.g. terrace and
        # open edge). Exact cited source names may distinguish them, but duplicate
        # named objects remain ambiguous even if the model requests only one ID.
        # A tight cited space label can establish its identity without pretending
        # that an approximate polygon is measured evidence. Other named objects
        # still participate in ambiguity checks, but cannot use this fallback.
        if len(matches) == 1 and matches[0][1] and matches[0][0].id in draft.highlight_ids:
            accepted.append(matches[0][0].id)
    return list(dict.fromkeys(accepted))


def whole_model_count_kind(question, *, single_building=False):
    """Only unqualified, explicitly scoped counts. No fuzzy qualifier stripping."""
    scope = r"(?:this|the|the uploaded) (?:ifc )?model"
    if single_building:
        scope = rf"(?:{scope}|(?:this|the) building)"
    match = re.fullmatch(
        rf"how many (windows|doors|walls|rooms|spaces) (?:are |are there )?in {scope}\??"
        rf"|how many (windows|doors|walls|rooms|spaces) does {scope} have\??",
        question.strip().lower(),
    )
    kinds = {"windows": "window", "doors": "door", "walls": "wall", "rooms": "room", "spaces": "room"}
    return kinds[match[1] or match[2]] if match else None
