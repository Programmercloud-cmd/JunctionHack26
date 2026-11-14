"""Select current and legacy format harnesses for evaluation only."""

from pathlib import Path

from VQA.couting_tasks._dispatch import run_count
from VQA.couting_tasks._ifc import count_ifc_direct
from VQA.couting_tasks._pdf import count_native_pdf
from VQA.couting_tasks.legacy.ifc_lookup import count_ifc_lookup
from VQA.couting_tasks.legacy.pdf_rendered import count_rendered_pdf


_HARNESSES = {
    "pdf-native": (".pdf", count_native_pdf),
    "pdf-rendered": (".pdf", count_rendered_pdf),
    "ifc-direct": (".ifc", count_ifc_direct),
    "ifc-lookup": (".ifc", count_ifc_lookup),
}


def count_with_harness(path, prompt, harness):
    suffix, task = _HARNESSES.get(harness, (None, None))
    return run_count(task if Path(path).suffix.lower() == suffix else None, path, prompt)
