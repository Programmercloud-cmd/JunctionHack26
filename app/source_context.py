"""Question-scoped structured source context; generated display geometry is not evidence."""
import json


def source_context(document, question=""):
    if document.question_context is not None:
        return json.dumps(document.question_context,ensure_ascii=False)
    from .reasoning import retrieve_context
    return json.dumps(retrieve_context(document,question),ensure_ascii=False)
