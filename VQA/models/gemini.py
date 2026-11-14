"""Google Gen AI adapter."""

import os
from mimetypes import guess_type
from pathlib import Path


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "boxes": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                "minItems": 4,
                "maxItems": 4,
            },
        },
    },
    "required": ["boxes"],
}


def complete(image_path: Path, prompt: str, model: str) -> str | None:
    from google import genai
    from google.genai import types

    image = types.Part.from_bytes(
        data=image_path.read_bytes(), mime_type=guess_type(image_path)[0],
    )
    with genai.Client(api_key=os.environ["GEMINI_API_KEY"], vertexai=False) as client:
        response = client.models.generate_content(
            model=model,
            contents=[image, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=_RESPONSE_SCHEMA,
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            ),
        )
    return response.text
