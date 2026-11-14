"""Temporary OpenAI adapter using a structured gate, not a native Decisions API."""
import base64
import json
from typing import Literal

from openai import OpenAI
from pydantic import Field

from .provider import (
    ANSWER_INSTRUCTIONS,
    CROP_INSTRUCTIONS,
    GATE_INSTRUCTIONS,
    ProviderError,
    settings,
    views,
    remaining_timeout, configured_number, RECONSTRUCTION_REVIEW_INSTRUCTIONS,
    RECONSTRUCTION_PATCH_INSTRUCTIONS, ANSWER_REVIEW_INSTRUCTIONS, ANSWER_REPAIR_INSTRUCTIONS,
)
from .schemas import CropRequest, DraftAnswer, GateResult, StrictModel, Usage
from .source_context import source_context


def _wire_model(schema):
    """OpenAI's strict wire has required fields; local models retain useful defaults."""
    def json_schema(cls,*args,**kwargs):
        value=schema.model_json_schema(*args,**kwargs)
        def strip(node):
            if isinstance(node,dict):
                node.pop("default",None)
                for child in node.values():strip(child)
            elif isinstance(node,list):
                for child in node:strip(child)
        strip(value)
        return value
    return type("Wire"+schema.__name__,(schema,),{"model_json_schema":classmethod(json_schema)})


class EvidenceDecision(StrictModel):
    decision: Literal["sufficient", "insufficient", "unclear"]


class WireDraftAnswer(DraftAnswer):
    # OpenAI strict schemas require all properties and do not accept string defaults.
    next_action: str = Field(max_length=2000)


CLASSIFICATION_RULES = """
Choose exactly one decision:
- sufficient: all essential evidence is present and interpretable; a direct answer or calculation can be supported.
- insufficient: essential information is absent from the inspected source material.
- unclear: legibility, ambiguity, contradictory evidence or uncertain scope/completeness prevents determination.
Do not supply an answer or confidence estimate. This is one overall evidence-sufficiency assessment.
"""


class OpenAIProvider:
    def __init__(self):
        config = settings("openai")
        if not config["api_key"]:
            raise ProviderError("OpenAI is not configured. Set OPENAI_API_KEY in .env.local and restart the server.", 503)
        self.model = config["model"]
        self.decision_model = config["decision_model"]
        self.client = OpenAI(api_key=config["api_key"], max_retries=0, timeout=45)
        self.usage = Usage()

    def close(self):
        self.client.close()

    def _parse(self, document, question, instruction, schema, *, crop=None, model=None, max_tokens=8192, timeout=45, extra_views=None, extra_data=None):
        content = [{"type": "input_text", "text": json.dumps({
            "question": question, "inspected_pages": [page.number for page in document.pages],
        })}]
        if context := source_context(document,question):
            content.append({"type": "input_text", "text": context})
        for label, png in views(document, crop):
            content.extend([
                {"type": "input_text", "text": label},
                {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(png).decode(), "detail": "high"},
            ])
        for label,png in extra_views or []:
            content.extend([{"type":"input_text","text":label},{"type":"input_image","image_url":"data:image/png;base64,"+base64.b64encode(png).decode(),"detail":"high"}])
        if extra_data is not None:content.append({"type":"input_text","text":json.dumps(extra_data,ensure_ascii=False)})
        try:
            response = self.client.responses.parse(
                model=model or self.model,
                instructions=instruction,
                input=[{"role": "user", "content": content}],
                text_format=_wire_model(schema),
                store=False,
                max_output_tokens=max_tokens,
                timeout=remaining_timeout(self,timeout),
            )
            if response.usage:
                self.usage.input_tokens += response.usage.input_tokens or 0
                self.usage.output_tokens += response.usage.output_tokens or 0
            if response.status != "completed":
                raise ProviderError("OpenAI returned an incomplete response. Please retry or simplify the question; no evidence conclusion was made.")
            if any(getattr(part, "type", None) == "refusal"
                   for item in response.output if getattr(item, "type", None) == "message"
                   for part in item.content):
                raise ProviderError("OpenAI declined this request. Try a narrower drawing question; no evidence conclusion was made.")
            result = response.output_parsed
            if not isinstance(result, schema):
                raise ProviderError("OpenAI did not return the required structured response. Please retry; no evidence conclusion was made.")
            return schema.model_validate(result.model_dump())
        except ProviderError:
            raise
        except Exception:
            # SDK exceptions may contain input content and credentials; do not expose or log them.
            raise ProviderError("OpenAI could not complete the request. Check model access, quota and network, then retry. No evidence conclusion was made.") from None

    def gate(self, document, question, crop=None):
        result = self._parse(document, question, GATE_INSTRUCTIONS + CLASSIFICATION_RULES,
                             EvidenceDecision, crop=crop, model=self.decision_model, max_tokens=2048)
        return GateResult(decision=result.decision, confidence=None)

    def choose_crop(self, document, question):
        return self._parse(document, question, CROP_INSTRUCTIONS, CropRequest, max_tokens=2048)

    def answer(self, document, question, gate, crop=None):
        result = self._parse(document, question,
                             ANSWER_INSTRUCTIONS + "\nNative IFC calculations must use native_calculation with original object/property references and {result}; code resolves numeric inputs." + f"\nOverall evidence decision: {gate.decision}.",
                             WireDraftAnswer, crop=crop)
        return DraftAnswer.model_validate(result.model_dump())

    def reconstruct(self, document, page=None):
        from dataclasses import replace
        from .building import BuildingDescription, BUILDING_PROMPT
        source = replace(document, scene=None,description=None,reasoning=None,question_context=None)
        return self._parse(source, "Describe every explicitly depicted floor across these original pages.",
                           BUILDING_PROMPT, BuildingDescription, max_tokens=configured_number("RECONSTRUCTION_MAX_TOKENS",65536,integer=True),timeout=configured_number("RECONSTRUCTION_CALL_SECONDS",300))

    def review_reconstruction(self, document, description, scene, *, previous_description=None, previous_scene=None, previous_review=None):
        from .review_schema import ReconstructionReview
        from .review_render import overlay_views,issue_crops
        images=overlay_views(document,scene)
        if previous_scene:images+=overlay_views(document,previous_scene,"Previous usable revision")
        if previous_review:images+=issue_crops(document,previous_review.issues)
        return self._parse(document,"Review source reconstruction and possible candidate regressions.",RECONSTRUCTION_REVIEW_INSTRUCTIONS,ReconstructionReview,
          timeout=configured_number("RECONSTRUCTION_REVIEW_SECONDS",120),max_tokens=configured_number("RECONSTRUCTION_REVIEW_TOKENS",16384,integer=True),extra_views=images,
          extra_data={"base_revision_id":document.revision_id,"description":description.model_dump(mode="json"),"previous_description":previous_description.model_dump(mode="json")if previous_description else None,"previous_review":previous_review.model_dump(mode="json")if previous_review else None,
            "actual_geometry_inventory":[{"id":e.id,"name":e.name,"representation":e.representation,"has_geometry":e.geometry is not None,"note":e.note}for e in scene.elements]})

    def patch_reconstruction(self, document, description, scene, review):
        from .review_schema import DescriptionPatch
        from .review_render import overlay_views,issue_crops
        return self._parse(document,"Propose only supported targeted description corrections.",RECONSTRUCTION_PATCH_INSTRUCTIONS,DescriptionPatch,
          timeout=configured_number("RECONSTRUCTION_CALL_SECONDS",300),max_tokens=configured_number("RECONSTRUCTION_MAX_TOKENS",65536,integer=True),extra_views=overlay_views(document,scene)+issue_crops(document,review.issues),
          extra_data={"base_revision_id":document.revision_id,"description":description.model_dump(mode="json"),"review":review.model_dump(mode="json")})

    def review_answer(self, document, question, draft, gate, crop=None, *, validation=None):
        from .review_schema import AnswerReview
        class Routing(StrictModel):
            decision: Literal["supported","contradicted","unsupported","unclear"]
        result=self._parse(document,question,ANSWER_REVIEW_INSTRUCTIONS+"\nReturn one routing judgment; no confidence score.",Routing,crop=crop,max_tokens=2048,
          extra_data={"draft":draft.model_dump(mode="json"),"gate":gate.model_dump(mode="json"),"validation":validation or{}})
        return AnswerReview(decision=result.decision,confidence=None)

    def revise_answer(self, document, question, draft, gate, review, crop=None, *, validation=None):
        result=self._parse(document,question,ANSWER_INSTRUCTIONS+"\n"+ANSWER_REPAIR_INSTRUCTIONS+f"\nOverall sufficiency decision: {gate.decision}.",WireDraftAnswer,crop=crop,
          extra_data={"previous_draft":draft.model_dump(mode="json"),"review":review.model_dump(mode="json"),"validation":validation or{}})
        return DraftAnswer.model_validate(result.model_dump())
