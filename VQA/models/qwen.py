"""Local Qwen3-VL adapter for CUDA."""

import os
from functools import lru_cache
from pathlib import Path


def complete(image_path: Path, prompt: str, model: str) -> str:
    import torch
    from PIL import Image

    with Image.open(image_path) as source:
        image = source.convert("RGB")

    processor, network = _load_model(model)
    messages = [{
        "role": "user",
        "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}],
    }]
    inputs = processor.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True,
        return_dict=True, return_tensors="pt",
    ).to(network.device)
    inputs.pop("token_type_ids", None)

    with torch.inference_mode():
        ids = network.generate(**inputs, max_new_tokens=2048, do_sample=False)
    generated = ids[:, inputs["input_ids"].shape[-1]:]
    return processor.batch_decode(generated, skip_special_tokens=True)[0]


@lru_cache(maxsize=1)
def _load_model(checkpoint: str):
    if checkpoint == "qwen-vl-max" or checkpoint.startswith("qwen-vl-max-"):
        raise ValueError(
            f"{checkpoint!r} is hosted on Alibaba Cloud Model Studio. "
            "The local Qwen adapter requires a Qwen3-VL Hub ID or checkpoint directory."
        )

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Local Qwen3-VL requires CUDA to be visible to PyTorch.")

    from transformers import AutoProcessor, Qwen3VLConfig, Qwen3VLForConditionalGeneration

    device = torch.device("cuda", torch.cuda.current_device())
    options = {
        "cache_dir": os.environ.get("QWEN_CACHE_DIR"),
        "local_files_only": os.environ.get("QWEN_LOCAL_FILES_ONLY") == "1",
    }
    checkpoint = os.path.expanduser(checkpoint)
    processor = AutoProcessor.from_pretrained(checkpoint, **options)
    config = Qwen3VLConfig.from_pretrained(checkpoint, **options)
    quantization = getattr(config, "quantization_config", None)
    if isinstance(quantization, dict) and quantization.get("quant_method") == "bitsandbytes":
        # Older checkpoints use the short name for the unquantized vision tower.
        skipped = quantization.get("llm_int8_skip_modules") or []
        if "visual" in skipped and "model.visual" not in skipped:
            quantization["llm_int8_skip_modules"] = [*skipped, "model.visual"]

    network = Qwen3VLForConditionalGeneration.from_pretrained(
        checkpoint, **options, config=config, use_safetensors=True, device_map={"": device},
        dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        attn_implementation="sdpa",
    ).eval()
    return processor, network
