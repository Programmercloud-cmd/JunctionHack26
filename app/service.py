"""Bounded question orchestration and deterministic evidence/calculation checks."""
import math
from time import monotonic

from .provider import ProviderError
from .schemas import Answer, DraftAnswer, Usage
from .highlights import validated_highlights, whole_model_count_kind
from .source_context import IFC_CONTEXT_PROPERTIES


def validate_draft(draft: DraftAnswer, document, gate, *, server_catalog_count=False):
    allowed_pages = {p.number for p in document.pages}
    if any(item.page not in allowed_pages for item in draft.evidence):
        raise ProviderError("The model returned a reference to an uninspected page. Please try a more specific question.")
    if draft.model_evidence:
        if document.kind != "ifc" or not document.scene or document.scene.derived:
            raise ProviderError("The model cited IFC evidence for a drawing. Please retry.")
        elements = {e.id: e for e in document.scene.elements}
        for ref in draft.model_evidence:
            if ref.element_id is None:
                if not server_catalog_count or not document.scene.catalog_complete or ref.property_name:
                    raise ProviderError("Catalog-only evidence is reserved for a server-computed zero count.")
            elif ref.element_id not in elements:
                raise ProviderError("The model cited an unknown IFC element.")
            elif ref.property_name and ref.property_name not in {p.name for p in elements[ref.element_id].properties[:IFC_CONTEXT_PROPERTIES]}:
                raise ProviderError("The model cited an unavailable IFC property.")
    if gate.decision != "sufficient" and draft.status != gate.decision:
        raise ProviderError("The model returned an answer inconsistent with the evidence assessment. Please retry or clarify the question.")
    if draft.status == "answered" and not (draft.evidence or draft.model_evidence):
        raise ProviderError("The model did not provide supporting source regions. Please try a more specific question.")
    if draft.proposal and draft.proposal.basis != "explicit_assumption":
        raise ProviderError("The model proposed an unverified reference building. Please retry without a comparison request.")
    if draft.proposal and draft.proposal.reference:
        raise ProviderError("The model returned an unsupported proposal reference. Please retry.")
    if draft.calculation:
        if draft.status != "answered" or "{result}" not in draft.answer:
            raise ProviderError("The model returned an incomplete calculation. Please rephrase the measurement question.")
        calculation = draft.calculation
        if any(v.evidence_index >= len(draft.evidence or draft.model_evidence) for v in calculation.operands):
            raise ProviderError("A calculation input lacks a source reference. Please provide clearer dimensions.")
        values = [v.value for v in calculation.operands]
        if calculation.operation == "sum":
            result = sum(values)
        elif calculation.operation == "product":
            result = math.prod(values)
        elif len(values) != 2:
            raise ProviderError("The model returned an invalid two-input calculation. Please retry.")
        elif calculation.operation == "difference":
            result = values[0] - values[1]
        elif values[1] == 0:
            raise ProviderError("The model returned a division by zero. Please provide clearer dimensions.")
        else:
            result = values[0] / values[1]
        if not math.isfinite(result):
            raise ProviderError("The model returned an invalid numerical calculation. Please retry.")
        draft.answer = draft.answer.replace("{result}", f"{result:.6g}")
    elif "{result}" in draft.answer:
        raise ProviderError("The model omitted the calculation inputs. Please retry.")
    draft.highlight_ids = validated_highlights(draft, document)


def ifc_count(document, kind):
    elements = [e for e in document.scene.elements if e.kind == kind]
    label = "spaces (IfcSpace)" if kind == "room" else kind + "s"
    evidence = [{"element_id": e.id, "label": (e.name or e.ifc_type or e.kind)[:200],
                 "observation": f"{e.ifc_type} record #{e.source.step_id} in the uploaded IFC."} for e in elements]
    if not evidence:
        evidence = [{"element_id": None, "label": "Complete IFC catalog",
                     "observation": f"No {label} records occur in the complete imported element catalog."}]
    return DraftAnswer(status="answered", answer=f"{len(elements)} {label} are recorded in the uploaded IFC model.",
                       model_evidence=evidence, highlight_ids=[e.id for e in elements])


def ask(document, question, provider):
    start = monotonic()
    crop = None
    passes = 1
    try:
        derived = bool(document.scene and document.scene.derived)
        if derived and not document.pages:
            raise ProviderError("Original drawing pages are required to answer questions about this derived IFC. No generated dimensions were used as evidence.")
        native_ifc = document.kind == "ifc" and not derived
        gate = provider.gate(document, question)
        if gate.decision == "unclear" and not native_ifc:
            crop = provider.choose_crop(document, question)
            if crop.page not in {p.number for p in document.pages}:
                raise ProviderError("The model selected an unavailable source page for inspection. Please retry.")
            left, top, right, bottom = crop.bbox
            # A near-whole-page repeat adds no targeted inspection. Keep unclear instead.
            if (right - left) * (bottom - top) < 0.9:
                gate = provider.gate(document, question, crop)
                passes = 2
            else:
                crop = None
        kind = whole_model_count_kind(question) if native_ifc else None
        server_catalog_count = bool(kind and gate.decision == "sufficient" and document.scene.catalog_complete)
        if server_catalog_count:
            draft = ifc_count(document, kind)
        else:
            draft = provider.answer(document, question, gate, crop)
        validate_draft(draft, document, gate, server_catalog_count=server_catalog_count)
        usage = provider.usage.model_copy()
        usage.latency_ms = round((monotonic() - start) * 1000)
        payload = draft.model_dump(exclude={"calculation"})
        return Answer(**payload, inspected_pages=[p.number for p in document.pages], gate=gate,
                      inspection_passes=passes, usage=usage)
    except ProviderError:
        raise
    except Exception:
        # Deliberately do not log provider exceptions: they can contain source text or credentials.
        raise ProviderError("The selected provider could not complete the request. Check model access, quota and network, then retry. No evidence conclusion was made.") from None
