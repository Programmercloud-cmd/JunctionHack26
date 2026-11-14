"""Render model bounding boxes on a copy of a blueprint."""

from PIL import Image, ImageDraw


def draw_bounding_boxes(image: Image.Image, boxes: list[list[int]]) -> Image.Image:
    """Return a copy with normalized [xmin, ymin, xmax, ymax] boxes drawn on it."""
    annotated = image.convert("RGB")
    draw = ImageDraw.Draw(annotated)
    x_scale = (annotated.width - 1) / 1000
    y_scale = (annotated.height - 1) / 1000

    for xmin, ymin, xmax, ymax in boxes:
        rectangle = (
            round(xmin * x_scale), round(ymin * y_scale),
            round(xmax * x_scale), round(ymax * y_scale),
        )
        draw.rectangle(rectangle, outline="#d60057", width=max(2, annotated.width // 700))

    return annotated
