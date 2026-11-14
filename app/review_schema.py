"""Data-only review and targeted-correction contracts; never executable model output."""
from typing import Literal
from pydantic import Field
from .schemas import StrictModel
from .building import (PageRegion, RoomDescription, BoundaryDescription, OpeningDescription,
                       FeatureDescription, UnresolvedDescription, FloorDescription)


class ReconstructionIssue(StrictModel):
    id: str
    object_ids: list[str] = Field(default_factory=list)
    source: PageRegion
    category: Literal["extraction", "generation", "display"]
    discrepancy: str
    evidence: str
    proposed_action: str
    actionable: bool
    uncertainty: str = ""


class ReconstructionReview(StrictModel):
    issues: list[ReconstructionIssue] = Field(default_factory=list)
    candidate_supported: bool
    summary: str


class RecordPatch(StrictModel):
    action: Literal["add", "replace", "remove"]
    collection: Literal["floors", "rooms", "boundaries", "openings", "features", "unresolved"]
    target_id: str | None = None
    floor_id: str | None = None
    record: RoomDescription | BoundaryDescription | OpeningDescription | FeatureDescription | UnresolvedDescription | FloorDescription | None = None
    evidence: PageRegion
    reason: str
    issue_ids: list[str] = Field(default_factory=list)


class TransformUpdate(StrictModel):
    floor_id: str
    evidence: PageRegion
    reason: str


class DescriptionPatch(StrictModel):
    base_revision_id: str
    operations: list[RecordPatch] = Field(default_factory=list)
    transform_updates: list[TransformUpdate] = Field(default_factory=list)


class AnswerReview(StrictModel):
    decision: Literal["supported", "contradicted", "unsupported", "unclear"]
    confidence: float | None = None
