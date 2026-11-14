"""Source interpretation and reviewed QA using a caller-owned provider."""

from collections.abc import Callable

from ..documents import Document
from ..schemas import Answer
from ..service import ask


class VLM:
    def __init__(self, provider):
        self.provider = provider

    def extract(self, source: Document):
        return self.provider.extract_interpretation(source, include_geometry=False)

    def answer(
        self, source: Document, question: str, *, progress: Callable[[str], None] | None = None
    ) -> Answer:
        return ask(source, question, self.provider, progress=progress)
