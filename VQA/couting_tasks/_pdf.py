"""Count on native or rasterized PDFs with page-linked evidence."""

import json
import re

from ._result import CountResult, INTEGER, TEXT, InvalidEvidence, UnsupportedCount, array_schema, object_schema, valid_box
from .models import gemini


EVIDENCE = object_schema(
    page=INTEGER,
    occurrence_id=TEXT,
    box=array_schema(INTEGER),
    excerpt=TEXT,
    value=INTEGER,
)
SCHEMA = object_schema(
    mode={"type": "string", "enum": ["instances", "total", "sum", "zero", "visual_zero", "unsupported"]},
    evidence=array_schema(EVIDENCE),
    inspected_pages=array_schema(INTEGER),
    reason=TEXT,
)
INSTRUCTIONS = """Answer a counting question using the supplied document. Inspect every page.
Page numbers are 1-based. Boxes use [xmin,ymin,xmax,ymax] integer coordinates
on 0–1000 normalized to the full page. Excerpts must exactly quote supplied
page text. Give each distinct occurrence a nonempty ID and reuse that ID if
it appears in more than one view.
Choose mode instances for a complete set of identified occurrences, each
with a tight box or a quoted row that identifies it. Choose total for one
explicit total in a source excerpt, or sum for complete nonoverlapping
subtotals explicitly stated in source excerpts. Give totals/subtotals
distinct IDs and values. Choose zero for an explicit statement or schedule
showing zero, and cite the zero-valued excerpt.
Choose visual_zero only if all relevant areas are clearly visible and you
inspected them and found no matching objects. Supply the 1-based inspected_pages
and briefly describe which views or areas and object symbols you checked in
reason. Use an empty evidence list in this mode. If the drawing is ambiguous,
the symbols cannot be distinguished, or the relevant areas are only partly
shown, choose unsupported and explain. Use an empty inspected_pages list for
other modes. An empty evidence list does not establish a count.
For unused fields use empty strings, empty boxes, and value -1. Never infer
a whole-building total from a partial view or invent evidence.
"""


def normalized(value):
    return " ".join(value.split())


def evidence_result(reply, pages):
    mode = reply.get("mode")
    if mode == "unsupported":
        raise UnsupportedCount(reply.get("reason") or "The document does not establish this count.")
    items = reply.get("evidence", [])
    if mode == "visual_zero":
        inspected = reply.get("inspected_pages")
        reason = reply.get("reason")
        if items != [] or not isinstance(inspected, list) or not inspected or any(
            type(page) is not int or not 1 <= page <= len(pages) for page in inspected
        ):
            raise InvalidEvidence("A visual zero requires valid inspected pages and no occurrence citations.")
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidEvidence("A visual zero requires an explanation of what was checked.")
        return CountResult(
            count=0,
            evidence=[{"kind": "pdf_visual_zero", "pages": sorted(set(inspected)), "reason": reason.strip()}],
            gaps=["Zero is based on visual inspection and has no independent source citation confirming absence."],
        )
    if not items:
        raise InvalidEvidence("The PDF response supplied no evidence or explicit visual-zero claim.")
    if mode not in {"instances", "total", "sum", "zero"}:
        raise UnsupportedCount("The proposed PDF counting mode is unsupported.")
    found = {}
    occurrences = set()
    values = {}
    locator_ids = {}
    subtotal_spans = {}
    page_text = [normalized(text) for text in pages]
    for item in items:
        page, identifier, box, excerpt, value = (
            item["page"], item["occurrence_id"], item["box"], item["excerpt"], item["value"]
        )
        if type(page) is not int or not 1 <= page <= len(pages) or not identifier.strip():
            raise InvalidEvidence("The proposed PDF evidence has an invalid page or occurrence ID.")
        identifier = identifier.strip()
        excerpt = normalized(excerpt)
        if excerpt and excerpt not in page_text[page - 1]:
            raise InvalidEvidence("A proposed quotation is absent from its cited page.")
        if box and not valid_box(box):
            raise InvalidEvidence("A proposed PDF bounding box is invalid.")
        locators = [(page, "box", tuple(box))] if box else []
        if excerpt and (not box or mode != "instances"):
            locators.append((page, "excerpt", excerpt))
        for locator in locators:
            if locator in locator_ids and locator_ids[locator] != identifier:
                raise InvalidEvidence("A PDF locator was reused for distinct occurrences or subtotals.")
            locator_ids[locator] = identifier
        if mode == "instances":
            if not (box or excerpt):
                raise InvalidEvidence("A proposed occurrence has no page evidence.")
            occurrences.add(identifier)
        else:
            if type(value) is not int or value < 0:
                raise InvalidEvidence("A proposed total has no nonnegative source value.")
            tokens = re.findall(r"(?<![\w.+-])[-+]?\d+(?:[.,]\d+)*(?!\w|[.,]\d)", excerpt)
            numbers = {token.replace(",", "") for token in tokens if re.fullmatch(r"\d+|\d{1,3}(,\d{3})+", token)}
            if str(value) not in numbers:
                raise InvalidEvidence("A proposed total is absent from its cited quotation.")
            if mode == "sum":
                source = page_text[page - 1]
                offset = source.index(excerpt)
                end = offset + len(excerpt)
                if source.find(excerpt, offset + 1) != -1:
                    raise InvalidEvidence("A subtotal quotation is ambiguous on its page.")
                for (prior_source, prior_start, prior_end), prior_id in subtotal_spans.items():
                    if prior_id != identifier and source == prior_source and offset < prior_end and prior_start < end:
                        raise InvalidEvidence("Distinct subtotals overlap the same source text.")
                subtotal_spans[source, offset, end] = identifier
            if identifier in values and values[identifier] != value:
                raise InvalidEvidence("A subtotal ID cites conflicting values.")
            values[identifier] = value
        key = (page, tuple(box), excerpt, identifier)
        found[key] = {
            "kind": "pdf", "page": page, "occurrence_id": identifier, "box": box or None,
            "excerpt": excerpt or None, "value": value if mode != "instances" else None,
        }
    if mode == "instances":
        count = len(occurrences)
    elif mode in {"total", "zero"} and len(values) == 1:
        count = next(iter(values.values()))
        if mode == "zero" and count != 0:
            raise InvalidEvidence("A zero claim cites a nonzero value.")
    elif mode == "sum":
        count = sum(values.values())
    else:
        raise UnsupportedCount("The proposed PDF aggregation is unsupported.")
    evidence = list(found.values())
    if mode != "instances":
        evidence.append({"kind": "pdf_aggregation", "operation": mode, "operands": values, "count": count})
    return CountResult(count=count, evidence=evidence, verified_zero=count == 0)


def count_native_pdf(path, question):
    return count_pdf(path, question, native_attachment)


def native_attachment(path, document):
    return [(path.read_bytes(), "application/pdf")], "The attachment contains all PDF pages in numerical order."


def count_pdf(path, question, make_attachments):
    import pymupdf

    with pymupdf.open(path) as document:
        pages = [page.get_text() for page in document]
        if not pages:
            raise UnsupportedCount("The PDF has no pages to inspect.")
        attachments, layout = make_attachments(path, document)
    prompt = (
        f"{INSTRUCTIONS}\n{layout}\nQuestion: {question}\nPage excerpts: "
        + json.dumps([{"page": number, "text": page} for number, page in enumerate(pages, 1)], ensure_ascii=False)
    )
    return evidence_result(gemini.structured(prompt, SCHEMA, attachments), pages)
