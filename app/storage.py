"""Galeria de objetos generados.

En el PC se usa el sistema de ficheros como base de datos a proposito: cero
dependencias, y puedes copiar o respaldar la carpeta data/models entera.

Cuando el backend corre en un hosting gratuito el disco es efimero, asi que
FOTO3D_STORAGE=hf redirige todo a un repositorio privado de Hugging Face
(ver hf_repo.py). El resto de la aplicacion no se entera del cambio.
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from . import config
from .providers.base import Generation

_META = "meta.json"


def _in_cloud() -> bool:
    return config.STORAGE == "hf"


def _hf():
    from . import hf_repo  # se importa solo si hace falta

    return hf_repo


def _meta_path(model_id: str) -> Path:
    return config.MODELS_DIR / model_id / _META


def _read_meta(folder: Path) -> dict | None:
    try:
        return json.loads((folder / _META).read_text(encoding="utf-8"))
    except Exception:
        return None


def save(gen: Generation, name: str, source_image: Path | None = None,
         user: str = "anon") -> dict:
    """Copia los ficheros generados a nuestra carpeta y escribe los metadatos."""
    if _in_cloud():
        return _hf().save(gen, name, source_image, user)

    model_id = uuid.uuid4().hex[:12]
    folder = config.MODELS_DIR / model_id
    folder.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(gen.glb_path, folder / "model.glb")

    # La foto recortada sin fondo es la mejor miniatura posible y sale gratis.
    thumb = gen.cutout_path or source_image
    if thumb and Path(thumb).exists():
        shutil.copyfile(thumb, folder / f"thumb{Path(thumb).suffix.lower()}")

    if gen.preview_video and gen.preview_video.exists():
        shutil.copyfile(gen.preview_video, folder / "preview.mp4")

    meta = {
        "id": model_id,
        "name": name,
        "created_at": time.time(),
        "provider": gen.provider,
        "size_bytes": (folder / "model.glb").stat().st_size,
        "has_video": (folder / "preview.mp4").exists(),
        "thumb": next((p.name for p in folder.glob("thumb.*")), None),
        "user": user,
    }
    (folder / _META).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def list_all(user: str | None = None) -> list[dict]:
    """Objetos del usuario, del mas reciente al mas antiguo.

    user=None devuelve todos: lo usan las tareas internas, nunca la API.
    """
    if _in_cloud():
        return _hf().list_all(user)
    items = [m for f in config.MODELS_DIR.iterdir() if f.is_dir() and (m := _read_meta(f))]
    if user is not None:
        items = [m for m in items if m.get("user", "anon") == user]
    return sorted(items, key=lambda m: m.get("created_at", 0), reverse=True)


def count_quick(user: str | None = None) -> int | None:
    """Numero de objetos sin tocar la red.

    Lo usa /api/health, al que la plataforma llama cada pocos segundos: si ese
    endpoint se pone a hablar con Hugging Face, tarda, y el servicio acaba
    reiniciandose en bucle. None significa "todavia no lo se".
    """
    if _in_cloud():
        return _hf().cached_count(user)
    try:
        if user is None:
            return sum(1 for f in config.MODELS_DIR.iterdir() if f.is_dir())
        return len(list_all(user))
    except Exception:
        return None


def get(model_id: str, user: str | None = None) -> dict | None:
    meta = _hf().get(model_id) if _in_cloud() else _read_meta(config.MODELS_DIR / model_id)
    # Nadie ve ni toca los objetos de otro.
    if meta is not None and user is not None and meta.get("user", "anon") != user:
        return None
    return meta


def file_path(model_id: str, filename: str) -> Path | None:
    """Ruta local de un fichero del objeto, lista para servir."""
    if _in_cloud():
        return _hf().local_path(model_id, filename)

    folder = (config.MODELS_DIR / model_id).resolve()
    target = (folder / filename).resolve()
    # Nadie sale de su carpeta: corta ../.. y rutas absolutas.
    if not str(target).startswith(str(config.MODELS_DIR.resolve())) or not target.is_file():
        return None
    return target


def rename(model_id: str, name: str, user: str | None = None) -> dict | None:
    if get(model_id, user) is None:
        return None
    if _in_cloud():
        return _hf().rename(model_id, name)
    meta = get(model_id)
    if meta is None:
        return None
    meta["name"] = name
    _meta_path(model_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def delete(model_id: str, user: str | None = None) -> bool:
    if get(model_id, user) is None:
        return False
    if _in_cloud():
        return _hf().delete(model_id)

    folder = config.MODELS_DIR / model_id
    # Comprobamos que sea una carpeta nuestra antes de borrar nada.
    if not (folder.is_dir() and (folder / _META).exists()):
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True
