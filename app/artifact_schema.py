"""Portable source provenance for our drawing-derived IFC artifacts."""
from typing import Literal
from .schemas import StrictModel
from .scene import Scene
from .building import BuildingDescription
from pydantic import Field

PSET_NAME = "Pset_BlueprintQA"
MANIFEST_PROPERTY = "Manifest"
ARTIFACT_MARKER = "BlueprintQA::DrawingDerived:v5"
DISPLAY_UNIT = "UNSCALED_DISPLAY_UNIT"


class EmbeddedPage(StrictModel):
    number: int
    source_id: str | None = None
    source_page: int | None = None
    width: int
    height: int
    sha256: str
    png_base64: str


class EmbeddedSource(StrictModel):
    source_id: str
    filename: str
    filenames: list[str] = Field(default_factory=list)
    kind: str
    media_type: str
    sha256: str
    original_base64: str
    pages: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ArtifactManifest(StrictModel):
    version: Literal[2, 3, 4, 5] = 5
    artifact_id: str
    source_filename: str
    pages: list[EmbeddedPage]
    scene: Scene
    description: BuildingDescription | None = None
    identity_registry: dict = Field(default_factory=dict)
    frame_registry: dict = Field(default_factory=dict)
    sources: list[EmbeddedSource] = Field(default_factory=list)
    user_values: list[dict] = Field(default_factory=list)
    source_interpretations: dict = Field(default_factory=dict)
    geometry_revision_id: str | None = None
