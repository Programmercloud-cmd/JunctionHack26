"""Gemini Hydrogen adapter for structured counting requests."""

import json
import os
from mimetypes import guess_type
from pathlib import Path

from .._result import INTEGER, array_schema, object_schema


MODEL = "gemini-4-hydrogen"
_BOX = {
    "type": "array",
    "items": {**INTEGER, "minimum": 0, "maximum": 1000},
    "minItems": 4,
    "maxItems": 4,
}
_RESPONSE_SCHEMA = object_schema(boxes=array_schema(_BOX))


def request(prompt, schema, attachments=()):
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        from dotenv import dotenv_values

        key = dotenv_values(Path(__file__).resolve().parents[3] / ".env").get("GEMINI_API_KEY")
    if not key:
        raise ValueError("Set GEMINI_API_KEY.")

    contents = [
        types.Part.from_bytes(data=data, mime_type=mime_type)
        for data, mime_type in attachments
    ]
    contents.append(prompt)
    with genai.Client(api_key=key, vertexai=False) as client:
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=schema,
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH if attachments else None,
            ),
        )
    return response.text


def structured(prompt, schema, attachments=()):
    answer = request(prompt, schema, attachments)
    if not answer or not answer.strip():
        raise ValueError("Gemini returned no structured answer.")
    answer = answer.strip()
    first_line, _, remainder = answer.partition("\n")
    if first_line.lower() in {"```json", "```"} and remainder.endswith("\n```"):
        answer = remainder[:-4].strip()
    return json.loads(answer)


def complete(image_path: Path, prompt: str, model: str, *, schema: dict = _RESPONSE_SCHEMA) -> str | None:
    if model != MODEL:
        raise ValueError(f"Use {MODEL} for VQA.")
    attachment = image_path.read_bytes(), guess_type(image_path)[0]
    return request(prompt, schema, [attachment])
