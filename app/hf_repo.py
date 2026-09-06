"""Galeria guardada en un repositorio privado de Hugging Face.

Los hostings gratuitos tienen disco efimero: al reiniciarse el servicio, todo
lo que hubieras escrito desaparece. Por eso, cuando el backend corre en la
nube, los modelos viven en un dataset privado de tu propia cuenta. Es gratis,
duradero, y usa el mismo token que ya hace falta para generar.

En el PC no se usa nada de esto: alli manda `storage.py` con el disco local.

Estructura dentro del repositorio:

    index.json                     lista con los metadatos de todos los objetos
    models/<id>/model.glb          el modelo 3D
    models/<id>/thumb.png          miniatura (la foto sin fondo)
    models/<id>/preview.mp4        video giratorio, si el motor lo genero
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from . import config
from .providers.base import Generation

_INDEX = "index.json"

# El backend es el unico que escribe en el repositorio, asi que basta con
# mantener el indice en memoria y reescribirlo cuando cambia. Evita bajarse
# el fichero en cada listado de la galeria.
_lock = threading.RLock()
_index: list[dict] | None = None


def _api() -> HfApi:
    if not config.HF_TOKEN:
        raise RuntimeError("La galeria en la nube necesita HF_TOKEN.")
    return HfApi(token=config.HF_TOKEN)


def _repo() -> str:
    if not config.HF_DATASET:
        raise RuntimeError("Falta FOTO3D_HF_DATASET (formato: usuario/nombre-del-repo).")
    return config.HF_DATASET


class NeedsWriteToken(RuntimeError):
    """El token solo tiene permiso de lectura y la galeria necesita escribir."""


def _friendly(exc: Exception) -> Exception:
    """El 403 de Hugging Face es criptico; aqui se explica que hay que hacer."""
    if "403" in str(exc) or "don't have the rights" in str(exc):
        return NeedsWriteToken(
            "El token de Hugging Face es de solo lectura y la galeria en la nube "
            "necesita escribir. Crea uno nuevo con permiso de Write en "
            "https://huggingface.co/settings/tokens y ponlo en el Space."
        )
    return exc


def ensure_repo() -> str:
    """Crea el repositorio si no existe. Privado siempre."""
    try:
        _api().create_repo(_repo(), repo_type="dataset", private=True, exist_ok=True)
    except Exception as exc:
        raise _friendly(exc) from exc
    return _repo()


def _push(local: Path | bytes, path_in_repo: str, message: str) -> None:
    try:
        _upload(local, path_in_repo, message)
    except Exception as exc:
        raise _friendly(exc) from exc


def _upload(local: Path | bytes, path_in_repo: str, message: str) -> None:
    _api().upload_file(
        path_or_fileobj=str(local) if isinstance(local, Path) else local,
        path_in_repo=path_in_repo,
        repo_id=_repo(),
        repo_type="dataset",
        commit_message=message,
    )


def _load_index() -> list[dict]:
    global _index
    with _lock:
        if _index is not None:
            return _index
        try:
            path = hf_hub_download(
                _repo(),
                _INDEX,
                repo_type="dataset",
                token=config.HF_TOKEN,
                force_download=True,
            )
            _index = json.loads(Path(path).read_text(encoding="utf-8")).get("models", [])
        except Exception:
            _index = []  # repositorio recien creado, todavia sin indice
        return _index


def _save_index(models: list[dict]) -> None:
    global _index
    with _lock:
        _index = models
        payload = json.dumps({"models": models}, ensure_ascii=False, indent=2).encode("utf-8")
        _push(payload, _INDEX, "Actualizar indice de la galeria")


def save(gen: Generation, name: str, source_image: Path | None = None) -> dict:
    ensure_repo()
    model_id = uuid.uuid4().hex[:12]
    folder = f"models/{model_id}"

    _push(Path(gen.glb_path), f"{folder}/model.glb", f"Modelo {model_id}")

    thumb_name = None
    thumb = gen.cutout_path or source_image
    if thumb and Path(thumb).exists():
        thumb_name = f"thumb{Path(thumb).suffix.lower()}"
        _push(Path(thumb), f"{folder}/{thumb_name}", f"Miniatura {model_id}")

    has_video = bool(gen.preview_video and Path(gen.preview_video).exists())
    if has_video:
        _push(Path(gen.preview_video), f"{folder}/preview.mp4", f"Vista previa {model_id}")

    meta = {
        "id": model_id,
        "name": name,
        "created_at": time.time(),
        "provider": gen.provider,
        "size_bytes": Path(gen.glb_path).stat().st_size,
        "has_video": has_video,
        "thumb": thumb_name,
    }

    with _lock:
        models = list(_load_index())
        models.append(meta)
        _save_index(models)
    return meta


def list_all() -> list[dict]:
    return sorted(_load_index(), key=lambda m: m.get("created_at", 0), reverse=True)


def get(model_id: str) -> dict | None:
    return next((m for m in _load_index() if m["id"] == model_id), None)


def rename(model_id: str, name: str) -> dict | None:
    with _lock:
        models = list(_load_index())
        for meta in models:
            if meta["id"] == model_id:
                meta["name"] = name
                _save_index(models)
                return meta
    return None


def delete(model_id: str) -> bool:
    with _lock:
        models = list(_load_index())
        target = next((m for m in models if m["id"] == model_id), None)
        if target is None:
            return False

        api = _api()
        names = ["model.glb"]
        if target.get("thumb"):
            names.append(target["thumb"])
        if target.get("has_video"):
            names.append("preview.mp4")
        for filename in names:
            try:
                api.delete_file(
                    path_in_repo=f"models/{model_id}/{filename}",
                    repo_id=_repo(),
                    repo_type="dataset",
                    commit_message=f"Borrar {filename} de {model_id}",
                )
            except Exception:
                pass  # ya no estaba; el indice manda

        _save_index([m for m in models if m["id"] != model_id])
        return True


def local_path(model_id: str, filename: str) -> Path | None:
    """Baja un fichero del repositorio (queda en cache) para poder servirlo."""
    try:
        return Path(
            hf_hub_download(
                _repo(),
                f"models/{model_id}/{filename}",
                repo_type="dataset",
                token=config.HF_TOKEN,
            )
        )
    except Exception:
        return None
