"""Reconocimiento del objeto fotografiado para ponerle nombre automaticamente.

Es OPCIONAL y nunca hace fallar una generacion: si no hay token, si el modelo
no responde o si tarda demasiado, se devuelve None y la app usa "Objeto N"
(que el usuario siempre puede renombrar a mano).

Necesita un token gratuito de Hugging Face en la variable HF_TOKEN.
"""
from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import httpx
from PIL import Image

from . import config

_ROUTER = "https://router.huggingface.co/v1/chat/completions"

# Se prueban en orden; el primero disponible en el nivel gratuito gana.
_VISION_MODELS = (
    "Qwen/Qwen2.5-VL-7B-Instruct",
    "meta-llama/Llama-3.2-11B-Vision-Instruct",
    "google/gemma-3-27b-it",
)

_PROMPT = (
    "Mira la foto y responde SOLO con el nombre del objeto principal en espanol, "
    "en 1 a 3 palabras, sin articulos, sin punto final y sin explicaciones. "
    "Ejemplos de respuesta valida: Taza de ceramica / Zapatilla deportiva / Silla de madera"
)


def _thumb_b64(image_path: Path, max_side: int = 512) -> str:
    """Reduce la foto antes de enviarla: mas rapido y gasta mucha menos cuota."""
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _clean(text: str) -> str | None:
    """El modelo a veces responde con comillas, prefijos o frases enteras."""
    name = text.strip().strip('".\'').split("\n")[0]
    name = re.sub(r"^(el|la|los|las|un|una|unos|unas)\s+", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" .,:;")
    if not name or len(name) > 40 or len(name.split()) > 4:
        return None
    return name[0].upper() + name[1:]


def guess_name(image_path: Path) -> str | None:
    """Devuelve un nombre para el objeto, o None si no se ha podido averiguar."""
    if not config.HF_TOKEN:
        return None

    try:
        data_url = "data:image/jpeg;base64," + _thumb_b64(image_path)
    except Exception:
        return None

    headers = {"Authorization": f"Bearer {config.HF_TOKEN}"}
    payload_messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": _PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }]

    for model in _VISION_MODELS:
        try:
            with httpx.Client(timeout=25.0) as client:
                resp = client.post(
                    _ROUTER,
                    headers=headers,
                    json={"model": model, "messages": payload_messages, "max_tokens": 24},
                )
            if resp.status_code != 200:
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            if name := _clean(content):
                return name
        except Exception:
            continue  # modelo no disponible en el nivel gratuito, probamos el siguiente
    return None
