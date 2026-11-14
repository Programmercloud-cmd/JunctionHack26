"""Bounded question orchestration and deterministic evidence/calculation checks."""
import math
import json
from copy import deepcopy
from time import monotonic

from .provider import ProviderError, configured_number
from .schemas import Answer, DraftAnswer, Usage, AnswerClaim, NativeCalculation
from .highlights import validated_highlights, whole_model_count_kind
from .reasoning import ensure_reasoning, retrieve_context, execute_native_calculation
from .review_schema import AnswerReview


def validate_draft(draft: DraftAnswer, document, gate, *, server_catalog_count=False):
    allowed_pages = {p.number for p in document.pages}
    if any(item.page not in allowed_pages for item in draft.evidence):
        raise ProviderError("The model returned a reference to an uninspected page. Please try a more specific question.")
    if draft.model_evidence:
        if document.kind != "ifc" or not document.scene or document.scene.derived:
            raise ProviderError("The model cited IFC evidence for a drawing. Please retry.")
        native_records={r["id"]:r for r in ensure_reasoning(document)["objects"]}
        inspected={r["id"]:r for r in (document.question_context or retrieve_context(document)).get("objects",[])}
        for ref in draft.model_evidence:
            if ref.element_id is None:
                if not server_catalog_count or not ensure_reasoning(document)["coverage"].get("catalog_complete") or ref.property_name:
                    raise ProviderError("Catalog-only evidence is reserved for a server-computed zero count.")
            elif ref.element_id not in native_records:
                raise ProviderError("The model cited an unknown IFC element.")
            elif ref.property_name and ref.property_name not in native_records[ref.element_id].get("values",{}):
                raise ProviderError("The model cited an unavailable IFC property.")
            elif ref.property_name and ref.property_name not in inspected.get(ref.element_id,{}).get("values",{}):
                raise ProviderError("The model cited an IFC property outside the inspected context.")
    if gate.decision != "sufficient" and draft.status != gate.decision:
        raise ProviderError("The model returned an answer inconsistent with the evidence assessment. Please retry or clarify the question.")
    if draft.status == "answered" and not (draft.evidence or draft.model_evidence):
        raise ProviderError("The model did not provide supporting source regions. Please try a more specific question.")
    if draft.proposal and draft.proposal.basis != "explicit_assumption":
        raise ProviderError("The model proposed an unverified reference building. Please retry without a comparison request.")
    if draft.proposal and draft.proposal.reference:
        raise ProviderError("The model returned an unsupported proposal reference. Please retry.")
    if draft.calculation:
        if document.kind=="ifc" and document.scene and not document.scene.derived:
            raise ProviderError("Native IFC calculations must reference original records; model-supplied numeric operands are not accepted.")
        if draft.status != "answered" or "{result}" not in draft.answer:
            raise ProviderError("The model returned an incomplete calculation. Please rephrase the measurement question.")
        calculation = draft.calculation
        if any(v.evidence_index >= len(draft.evidence or draft.model_evidence) for v in calculation.operands):
            raise ProviderError("A calculation input lacks a source reference. Please provide clearer dimensions.")
        values = [v.value for v in calculation.operands]
        units=[v.unit for v in calculation.operands]
        if any(units) and calculation.operation in {"sum","difference"} and len(set(units))!=1:
            raise ProviderError("Calculation inputs have incompatible or missing units.")
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


def _assign_claims(draft):
    texts=[claim.text for claim in draft.claims]or[draft.answer]
    draft.claims=[AnswerClaim(id=f"claim:{i}",text=text)for i,text in enumerate(texts)]
    if draft.status=="answered":draft.answer="\n".join(texts)


def _citation_identity(draft):
    return ({(e.page,tuple(e.bbox))for e in draft.evidence},
            {(e.element_id,e.property_name)for e in draft.model_evidence})


def _meaningful_repair(old,new,*,new_evidence,old_validation,new_validation):
    """Changing wording alone never establishes corrective progress."""
    if new.retained_claim_ids is not None:
        prior={c.id:c.text for c in old.claims}
        retained=list(dict.fromkeys(new.retained_claim_ids))
        if not set(retained)<set(prior):return False
        if not retained and new.status=="answered":return False
        new.claims=[AnswerClaim(id=i,text=prior[i])for i in retained]
        if retained:new.answer="\n".join(c.text for c in new.claims)
        return True
    if old.status=="answered"and new.status in {"insufficient","unclear"}:return True
    if new_evidence:return True
    if old_validation.get("errors")and not new_validation.get("errors"):
        if _citation_identity(old)!=_citation_identity(new):return True
        if old.calculation!=new.calculation or old.native_calculation!=new.native_calculation:return True
    return False


def _native_calculation(draft,document,question):
    if document.kind!="ifc"or not document.scene or document.scene.derived:return []
    kind=whole_model_count_kind(question)
    if kind and draft.status=="answered":
        # Full-model counts are always computed from the complete semantic catalog.
        draft.native_calculation=NativeCalculation(operation="count",scope="model",entity_type={"wall":"IfcWall","door":"IfcDoor","window":"IfcWindow","room":"IfcSpace"}[kind])
    if not draft.native_calculation:return []
    if draft.status!="answered":raise ProviderError("A refusal must not publish a native calculation.")
    result=execute_native_calculation(ensure_reasoning(document),draft.native_calculation)
    if result["status"]!="complete":return [result]
    refs=result["contributing_records"]
    from .schemas import ModelEvidence
    records={r["id"]:r for r in document.reasoning["objects"]}
    draft.model_evidence=[ModelEvidence(element_id=r["object_id"],property_name=r["property_name"],label=records[r["object_id"]]["name"][:200],observation=result["method"])for r in refs]
    if not refs:
        draft.model_evidence=[ModelEvidence(element_id=None,label="Complete IFC catalog",observation=result["method"])]
    draft.highlight_ids=list(dict.fromkeys(r["object_id"]for r in refs))
    # Calculations inspect their bound original inputs server-side. Expose those exact
    # records to the independent review, including values omitted by retrieval.
    if document.question_context is not None:
        inspected={r["id"]:r for r in document.question_context.get("objects",[])}
        for ref in refs:
            rid=ref["object_id"]
            if rid not in inspected:inspected[rid]=deepcopy(records[rid])
            elif ref["property_name"]:
                inspected[rid].setdefault("values",{})[ref["property_name"]]=deepcopy(records[rid]["values"][ref["property_name"]])
        document.question_context["objects"]=list(inspected.values())
    if kind:
        label="spaces (IfcSpace)"if kind=="room"else kind+"s"
        draft.answer=f"{result['value']} {label} are recorded in the uploaded IFC model."
    elif "{result}"not in draft.answer:
        raise ProviderError("Native calculation answer needs the deterministic {result} placeholder.")
    else:draft.answer=draft.answer.replace("{result}",f"{result['value']:.6g}")
    draft.claims=[AnswerClaim(id="claim:0",text=draft.answer)]
    return [result]


def _validate_internal(draft,document,question,gate):
    findings={"errors":[],"calculations":[]}
    try:
        findings["calculations"]=_native_calculation(draft,document,question)
        if any(r["status"]!="complete"for r in findings["calculations"]):
            raise ProviderError("Incomplete native calculation: "+" ".join(m for r in findings["calculations"]for m in r["missing_inputs"]))
        count=bool(draft.native_calculation and draft.native_calculation.operation=="count")
        validate_draft(draft,document,gate,server_catalog_count=count)
    except ProviderError as error:findings["errors"].append(error.message)
    return findings


def ask(document, question, provider, progress=None):
    start = monotonic()
    crop = None
    passes = 1
    document=document.snapshot()
    legacy_fixture=bool(getattr(provider,"legacy_fixture_without_review",False))
    deadline=start+configured_number("QA_TOTAL_SECONDS",180)
    provider.request_deadline=deadline
    def stage(name):
        if monotonic()>=deadline:raise ProviderError("The configured Q&A execution budget was exhausted. No unsupported draft was published.",504)
        if progress:progress(name)
    try:
        derived = bool(document.scene and document.scene.derived)
        if derived and not document.pages:
            raise ProviderError("Original drawing pages are required to answer questions about this derived IFC. No generated dimensions were used as evidence.")
        native_ifc = document.kind == "ifc" and not derived
        document.question_context=retrieve_context(document,question)
        stage("Inspecting source")
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
        stage("Drafting answer")
        if server_catalog_count and legacy_fixture:
            draft = ifc_count(document, kind)
        else:
            draft = provider.answer(document, question, gate, crop)
        if legacy_fixture:
            validate_draft(draft,document,gate,server_catalog_count=server_catalog_count)
            findings={"errors":[],"calculations":[]};review=None;review_passes=0
        else:
            if not callable(getattr(provider,"review_answer",None))or not callable(getattr(provider,"revise_answer",None)):
                raise ProviderError("The configured provider does not implement required answer review.",503)
            _assign_claims(draft)
            findings=_validate_internal(draft,document,question,gate)
            stage("Checking answer")
            review=provider.review_answer(document,question,draft,gate,crop,validation=findings)
            review_passes=1
            if review.decision!="supported"or findings["errors"]:
                old=draft.model_copy(deep=True);old_findings=deepcopy(findings);new_evidence=False
                if not native_ifc and crop is None:
                    stage("Inspecting additional source")
                    proposed=provider.choose_crop(document,question)
                    if proposed.page in {p.number for p in document.pages}and(proposed.bbox[2]-proposed.bbox[0])*(proposed.bbox[3]-proposed.bbox[1])<.9:
                        crop=proposed;new_evidence=True;passes+=1
                elif native_ifc:
                    # Reveal complete values of already selected original records, never inferred geometry.
                    expanded=deepcopy(document.question_context)
                    originals={r["id"]:r for r in ensure_reasoning(document)["objects"]}
                    expanded["objects"]=[originals[r["id"]]for r in expanded["objects"]]
                    if expanded["objects"]!=document.question_context["objects"]:
                        new_evidence=any(r.get("omitted_value_count",0)>0 for r in document.question_context["objects"])
                        expanded["retrieval"]["property_view_complete"]=True
                        document.question_context=expanded
                if new_evidence and gate.decision!="sufficient":
                    # A contradicted refusal is revisitable only after actual additional
                    # inspection. Preserve one overall gate rather than treating its
                    # first result as immutable truth.
                    stage("Reassessing source sufficiency")
                    gate=provider.gate(document,question,crop)
                stage("Correcting answer")
                revised=provider.revise_answer(document,question,old,gate,review,crop,validation=old_findings)
                findings=_validate_internal(revised,document,question,gate)
                if _meaningful_repair(old,revised,new_evidence=new_evidence,old_validation=old_findings,new_validation=findings):
                    draft=revised
                    # Claim removal may replace prose; validate the actual text being reviewed again.
                    if revised.retained_claim_ids is not None:
                        # The calculation was already resolved; recheck the composed claim
                        # text and evidence without executing its placeholder a second time.
                        try:validate_draft(draft,document,gate,server_catalog_count=bool(draft.native_calculation and draft.native_calculation.operation=="count"))
                        except ProviderError as error:findings["errors"].append(error.message)
                    stage("Checking corrected answer")
                    review=provider.review_answer(document,question,draft,gate,crop,validation=findings);review_passes=2
                else:
                    findings["errors"].append("No material correction: rephrasing the same unsupported assertion is not progress.")
                if review.decision!="supported"or findings["errors"]:
                    status=gate.decision if gate.decision!="sufficient"else"unclear"
                    draft=DraftAnswer(status=status,answer="I could not establish a reliable answer from the inspected source evidence. The internal draft was not published.",
                        missing_information=["Source support resolving the draft review and validation findings."],next_action="Inspect the cited material or provide the missing source detail.")
                    # Retain only individually valid original citations; never carry rejected highlights.
                    for evidence in old.evidence:
                        if evidence.page in {p.number for p in document.pages}:draft.evidence.append(evidence)
                    if native_ifc:
                        available={r["id"]for r in document.reasoning["objects"]}
                        draft.model_evidence=[e for e in old.model_evidence if e.element_id in available and not e.property_name]
        usage = provider.usage.model_copy()
        usage.latency_ms = round((monotonic() - start) * 1000)
        payload = draft.model_dump(exclude={"calculation","native_calculation","claims","retained_claim_ids"})
        stage("Complete")
        return Answer(**payload, inspected_pages=[p.number for p in document.pages], gate=gate,
                      inspection_passes=passes, usage=usage,building_id=document.building_id or document.id,
                      answered_revision_id=document.revision_id,display_revision_id=document.revision_id,
                      review_decision=review.decision if review else None,review_passes=review_passes,
                      review_note="Legacy fixture: answer review intentionally disabled."if legacy_fixture else("Original-evidence review is corroboration, not proof of correctness."if review.decision=="supported"and not findings["errors"]else"Draft remained unresolved; no rejected factual answer was published."),
                      calculation_results=findings["calculations"])
    except ProviderError:
        raise
    except Exception:
        # Deliberately do not log provider exceptions: they can contain source text or credentials.
        raise ProviderError("The selected provider could not complete the request. Check model access, quota and network, then retry. No evidence conclusion was made.") from None
