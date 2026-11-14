"""Portable source provenance for our drawing-derived IFC artifacts."""
from typing import Literal
from .schemas import StrictModel
from .scene import Scene
from .building import BuildingDescription

PSET_NAME = "Pset_BlueprintQA"
MANIFEST_PROPERTY = "Manifest"
ARTIFACT_MARKER = "BlueprintQA::DrawingDerived:v3"
DISPLAY_UNIT = "UNSCALED_DISPLAY_UNIT"


class EmbeddedPage(StrictModel):
    number: int
    width: int
    height: int
    sha256: str
    png_base64: str


class ArtifactManifest(StrictModel):
    version: Literal[2, 3] = 3
    artifact_id: str
    source_filename: str
    pages: list[EmbeddedPage]
    scene: Scene
    description: BuildingDescription | None = None
