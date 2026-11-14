"""Small explicit contracts shared by the HTTP and model boundaries."""
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AskRequest(StrictModel):
    document_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2000)
    revision_id: str | None = None
    request_id: str | None = None

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value


class Evidence(StrictModel):
    page: int = Field(ge=1, le=5)
    bbox: list[float] = Field(min_length=4, max_length=4)
    label: str = Field(min_length=1, max_length=200)
    observation: str = Field(min_length=1, max_length=1000)

    @field_validator("bbox")
    @classmethod
    def valid_box(cls, box):
        left, top, right, bottom = box
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in box):
            raise ValueError("Evidence coordinates must be finite and normalized")
        if left >= right or top >= bottom:
            raise ValueError("Evidence must have positive area")
        return box


class Proposal(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    basis: Literal["explicit_assumption", "reference"]
    reference: str | None = None


class Operand(StrictModel):
    value: float
    evidence_index: int = Field(ge=0)
    unit: str | None = None


class Calculation(StrictModel):
    operation: Literal["sum", "product", "difference", "quotient"]
    operands: list[Operand] = Field(min_length=2, max_length=20)
    unit: str = Field(min_length=1, max_length=40)


class ModelEvidence(StrictModel):
    element_id: str | None = None
    label: str = Field(min_length=1, max_length=200)
    observation: str = Field(min_length=1, max_length=2000)
    property_name: str | None = None


class NativeOperand(StrictModel):
    object_id: str
    property_name: str


class NativeCalculation(StrictModel):
    operation: Literal["count", "sum", "difference", "product", "quotient"]
    scope: Literal["model", "storey", "objects"]
    entity_type: str | None = None
    storey_id: str | None = None
    object_ids: list[str] = Field(default_factory=list)
    property_name: str | None = None
    operands: list[NativeOperand] = Field(default_factory=list)


class AnswerClaim(StrictModel):
    id: str | None = None
    text: str


class DraftAnswer(StrictModel):
    status: Literal["answered", "insufficient", "unclear"]
    answer: str = Field(min_length=1, max_length=6000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    next_action: str = Field(default="", max_length=2000)
    proposal: Proposal | None = None
    calculation: Calculation | None = None
    highlight_ids: list[str] = Field(default_factory=list, max_length=4000)
    model_evidence: list[ModelEvidence] = Field(default_factory=list, max_length=4000)
    native_calculation: NativeCalculation | None = None
    claims: list[AnswerClaim] = Field(default_factory=list)
    retained_claim_ids: list[str] | None = None


class CropRequest(StrictModel):
    page: int = Field(ge=1, le=5)
    bbox: list[float] = Field(min_length=4, max_length=4)
    reason: str = Field(min_length=1, max_length=1000)

    _valid_box = field_validator("bbox")(Evidence.valid_box.__func__)


class GateResult(StrictModel):
    decision: Literal["sufficient", "insufficient", "unclear"]
    confidence: float | None = Field(default=None, ge=0, le=1)


class Usage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)


class Answer(StrictModel):
    status: Literal["answered", "insufficient", "unclear"]
    answer: str
    evidence: list[Evidence]
    missing_information: list[str]
    next_action: str
    proposal: Proposal | None
    inspected_pages: list[int]
    gate: GateResult
    inspection_passes: int
    usage: Usage
    highlight_ids: list[str] = Field(default_factory=list)
    model_evidence: list[ModelEvidence] = Field(default_factory=list)
    building_id: str | None = None
    answered_revision_id: str | None = None
    display_revision_id: str | None = None
    review_decision: str | None = None
    review_passes: int = 0
    review_note: str = ""
    calculation_results: list[dict] = Field(default_factory=list)
