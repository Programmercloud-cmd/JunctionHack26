"""Source interpretation and reviewed QA using a caller-owned provider."""

from collections.abc import Callable

from ..documents import Document
from ..schemas import Answer, ChatQuestionIntent
from ..service import ask


class VLM:
    def __init__(self, provider):
        self.provider = provider

    def extract(self, source: Document):
        return self.provider.extract_interpretation(source, include_geometry=False)

    def answer(
        self, source: Document, question: str, *, progress: Callable[[str], None] | None = None,
        allow_3d: bool = False,
    ) -> Answer | ChatQuestionIntent:
        return ask(source, question, self.provider, progress=progress, allow_3d=allow_3d)
