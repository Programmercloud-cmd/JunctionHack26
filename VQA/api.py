"""Public VQA interface."""

from pathlib import Path as _Path

from .couting_tasks._dispatch import run_count as _run_count
from .couting_tasks._ifc import count_ifc_direct as _count_ifc
from .couting_tasks._image import count_image as _count_image
from .couting_tasks._pdf import count_native_pdf as _count_pdf
from .couting_tasks._result import CountResult as _CountResult
from .couting_tasks.models.gemini import MODEL as _MODEL

__all__ = ["count_objects"]


def count_objects(
    image_path: str | _Path, prompt: str, provider: str = "gemini", model: str = _MODEL,
) -> _CountResult:
    """Count objects in PNG, JPEG, PDF, or native IFC using Gemini Hydrogen.

    Results can be unpacked as (count, boxes). Image boxes use normalized
    [xmin, ymin, xmax, ymax]. PDF and IFC locators live in result.evidence.
    Unavailable counts use None and include a status and reason.
    """
    if provider != "gemini" or model != _MODEL:
        return _CountResult(status="unsupported", detail=f"Use gemini/{_MODEL} for VQA.")
    task = {
        ".png": _count_image, ".jpg": _count_image, ".jpeg": _count_image,
        ".pdf": _count_pdf, ".ifc": _count_ifc,
    }.get(_Path(image_path).suffix.lower())
    return _run_count(task, image_path, prompt)
