"""Data-only review and targeted-correction contracts; never executable model output."""
from typing import Literal, Annotated, Union
from pydantic import Field
from .schemas import StrictModel
from .building import (PageRegion, RoomDescription, BoundaryDescription, OpeningDescription,
                       FeatureDescription, UnresolvedDescription, FloorDescription, Calibration, Alignment, Registration, Measurement)


class ReconstructionIssue(StrictModel):
    id: str
    object_ids: list[str] = Field(default_factory=list)
    source: PageRegion = Field(description="Contextual original-page AREA with normalized 0..1 coordinates, left < right and top < bottom. Even a line-shaped boundary/opening issue must cite an inspected positive-width AND positive-height area, never a zero-area line.")
    category: Literal["extraction", "generation", "display"]
    discrepancy: str
    evidence: str
    proposed_action: str
    actionable: bool
    uncertainty: str = ""


class IssueResolution(StrictModel):
    issue_id: str
    evidence: PageRegion
    reason: str


class CandidateAssessment(StrictModel):
    delta_support: Literal["supported", "unsupported", "unclear"]
    source_conflicts: list[str]
    new_regressions: list[str]
    pre_existing_issue_ids: list[str]
    unresolved: list[str]
    issue_resolutions: list[IssueResolution] = Field(default_factory=list)


class ReconstructionReview(StrictModel):
    issues: list[ReconstructionIssue] = Field(default_factory=list)
    candidate_supported: bool
    summary: str
    candidate_assessment: CandidateAssessment | None = None


class RecordPatch(StrictModel):
    action: Literal["add", "replace", "remove"]
    collection: Literal["floors", "rooms", "boundaries", "openings", "features", "unresolved"]
    target_id: str | None = None
    floor_id: str | None = None
    record: RoomDescription | BoundaryDescription | OpeningDescription | FeatureDescription | UnresolvedDescription | FloorDescription | None = None
    evidence: PageRegion = Field(description="Contextual original-page area: left < right and top < bottom, each normalized 0..1. A line-shaped record.source is allowed for boundaries/openings but must NOT be copied here as zero-area evidence.")
    reason: str
    issue_ids: list[str] = Field(default_factory=list)


class TransformUpdate(StrictModel):
    floor_id: str
    evidence: PageRegion = Field(description="Contextual original-page area: left < right and top < bottom, each normalized 0..1. A line-shaped record.source is allowed for boundaries/openings but must NOT be copied here as zero-area evidence.")
    reason: str


class ChangeLabel(StrictModel):
    field: Literal["label"]
    value: str


class ChangeSource(StrictModel):
    field: Literal["source"]
    value: PageRegion


class ChangeOrder(StrictModel):
    field: Literal["order"]
    value: int | None


class ChangeOrderBasis(StrictModel):
    field: Literal["order_basis"]
    value: str


class ChangeRotationDegrees(StrictModel):
    field: Literal["rotation_degrees"]
    value: float | None


class ChangeOrientationBasis(StrictModel):
    field: Literal["orientation_basis"]
    value: str


class ChangeCalibration(StrictModel):
    field: Literal["calibration"]
    value: Calibration | None


class ChangeAlignment(StrictModel):
    field: Literal["alignment"]
    value: Alignment | None


class ChangeRegistration(StrictModel):
    field: Literal["registration"]
    value: Registration | None


class ChangeHeight(StrictModel):
    field: Literal["height"]
    value: Measurement | None


MetadataChange = Annotated[Union[ChangeLabel, ChangeSource, ChangeOrder, ChangeOrderBasis, ChangeRotationDegrees, ChangeOrientationBasis, ChangeCalibration, ChangeAlignment, ChangeRegistration, ChangeHeight], Field(discriminator="field")]

class FloorMetadataUpdate(StrictModel):
    floor_id: str
    changes: list[MetadataChange]
    evidence: PageRegion
    reason: str
    issue_ids: list[str] = Field(default_factory=list)


class AdditionalTargetRequest(StrictModel):
    request_id: str
    base_revision_id: str
    issue_id: str
    target_id: str
    floor_id: str | None
    collection: Literal["floors", "rooms", "boundaries", "openings", "features", "unresolved"]
    evidence: PageRegion
    reason: str


class TargetDecision(StrictModel):
    request_id: str
    issue_id: str
    target_id: str
    decision: Literal["approved", "denied", "unclear"]
    evidence: PageRegion
    reason: str


class AuthorizationReview(StrictModel):
    base_revision_id: str
    decisions: list[TargetDecision]


class DescriptionPatch(StrictModel):
    base_revision_id: str
    operations: list[RecordPatch] = Field(default_factory=list)
    floor_metadata_updates: list[FloorMetadataUpdate] = Field(default_factory=list)
    additional_target_requests: list[AdditionalTargetRequest] = Field(default_factory=list)
    transform_updates: list[TransformUpdate] = Field(default_factory=list)


class AnswerReview(StrictModel):
    decision: Literal["supported", "contradicted", "unsupported", "unclear"]
    confidence: float | None = None
