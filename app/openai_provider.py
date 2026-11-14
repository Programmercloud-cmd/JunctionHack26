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
)
from .schemas import CropRequest, DraftAnswer, GateResult, StrictModel, Usage
from .source_context import source_context


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

    def _parse(self, document, question, instruction, schema, *, crop=None, model=None, max_tokens=8192, timeout=45):
        content = [{"type": "input_text", "text": json.dumps({
            "question": question, "inspected_pages": [page.number for page in document.pages],
        })}]
        if context := source_context(document):
            content.append({"type": "input_text", "text": context})
        for label, png in views(document, crop):
            content.extend([
                {"type": "input_text", "text": label},
                {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(png).decode(), "detail": "high"},
            ])
        try:
            response = self.client.responses.parse(
                model=model or self.model,
                instructions=instruction,
                input=[{"role": "user", "content": content}],
                text_format=schema,
                store=False,
                max_output_tokens=max_tokens,
                timeout=timeout,
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
            return result
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
                             ANSWER_INSTRUCTIONS + f"\nOverall evidence decision: {gate.decision}.",
                             WireDraftAnswer, crop=crop)
        return DraftAnswer.model_validate(result.model_dump())

    def reconstruct(self, document, page=None):
        from dataclasses import replace
        from .building import BuildingDescription, BUILDING_PROMPT
        source = replace(document, scene=None)
        return self._parse(source, "Describe every explicitly depicted floor across these original pages.",
                           BUILDING_PROMPT, BuildingDescription, max_tokens=32768, timeout=150)
