"""Kimi adapter for Verda's Chat Completions endpoint."""

import os
from base64 import b64encode
from mimetypes import guess_type
from pathlib import Path


def complete(image_path: Path, prompt: str, model: str) -> str | None:
    from openai import OpenAI

    mime_type = guess_type(image_path)[0]
    encoded = b64encode(image_path.read_bytes()).decode("ascii")
    with OpenAI(
        base_url="https://inference.verda.com/v1",
        api_key=os.environ["VERDA_INFERENCE_API_KEY"],
        timeout=180,
    ) as client:
        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            response_format={"type": "json_object"},
        )
    return response.choices[0].message.content
