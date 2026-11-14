"""Legacy PDF harness that sends rasterized pages to Gemini."""

from .._pdf import count_pdf


def rendered_attachments(path, document):
    attachments = [
        (page.get_pixmap(dpi=150, alpha=False).tobytes("png"), "image/png")
        for page in document
    ]
    return attachments, f"Each successive image is a complete page, numbered from 1 through {len(document)}."


def count_rendered_pdf(path, question):
    return count_pdf(path, question, rendered_attachments)
