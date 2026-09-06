"""API del servidor. El movil habla solo con estos endpoints."""
from __future__ import annotations

import mimetypes
import socket
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config, jobs, storage
from .providers.hf_space import ALL as PROVIDERS


@asynccontextmanager
async def lifespan(app: FastAPI):
    _banner()
    yield


app = FastAPI(title="Foto3D", version="1.0.0", lifespan=lifespan)

# Python no conoce estas extensiones y serviria los modelos como texto plano.
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")

# App personal en red local: no hace falta restringir origenes.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class RenameBody(BaseModel):
    name: str


def require_key(x_foto3d_key: str | None = Header(default=None)) -> None:
    """Puerta de entrada cuando el backend esta publicado en internet.

    Sin FOTO3D_API_KEY no se comprueba nada, que es lo comodo en la red de
    casa. Con ella, la app tiene que mandar la misma clave en la cabecera.
    """
    if config.API_KEY and x_foto3d_key != config.API_KEY:
        raise HTTPException(401, "Clave incorrecta o ausente.")


# /api/health se deja abierto a proposito: la pantalla de Ajustes lo usa para
# decirte si el servidor responde, y no revela nada sensible.
guard = [Depends(require_key)]


@lru_cache(maxsize=1)
def lan_ip() -> str:
    """IP de esta maquina en la red local, para que el movil sepa a donde ir.

    Cacheada: la llama /api/health, que debe ser instantaneo."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


@app.get("/api/health")
def health() -> dict:
    """Tiene que ser instantaneo: la plataforma lo llama como health check y,
    si tarda, mata el contenedor y lo reinicia una y otra vez."""
    return {
        "ok": True,
        "providers": [PROVIDERS[n].label for n in config.PROVIDER_ORDER if n in PROVIDERS],
        "auto_naming": bool(config.HF_TOKEN),
        "models": storage.count_quick(),
        "lan_ip": lan_ip(),
        "storage": config.STORAGE,
    }


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp")


@app.post("/api/generate", dependencies=guard)
async def generate(photo: UploadFile = File(...)) -> dict:
    # El subidor nativo de expo-file-system no siempre manda content-type,
    # asi que la extension tambien vale como prueba de que es una imagen.
    content_type = (photo.content_type or "").lower()
    filename = (photo.filename or "").lower()
    if not (content_type.startswith("image/") or filename.endswith(IMAGE_SUFFIXES)):
        raise HTTPException(415, "El fichero enviado no es una imagen.")

    suffix = Path(photo.filename or "foto.jpg").suffix.lower() or ".jpg"
    if suffix not in IMAGE_SUFFIXES:
        suffix = ".jpg"
    dest = config.UPLOADS_DIR / f"{int(time.time() * 1000)}{suffix}"
    dest.write_bytes(await photo.read())

    fallback = f"Objeto {len(storage.list_all()) + 1}"
    job = jobs.submit(dest, fallback)
    return {"job_id": job.id, "status": job.status}


@app.get("/api/jobs/{job_id}", dependencies=guard)
def job_status(job_id: str) -> dict:
    if (job := jobs.get(job_id)) is None:
        raise HTTPException(404, "Trabajo no encontrado.")
    return job


@app.get("/api/models", dependencies=guard)
def list_models() -> list[dict]:
    return storage.list_all()


@app.get("/api/models/{model_id}", dependencies=guard)
def get_model(model_id: str) -> dict:
    if (meta := storage.get(model_id)) is None:
        raise HTTPException(404, "Objeto no encontrado.")
    return meta


@app.patch("/api/models/{model_id}", dependencies=guard)
def rename_model(model_id: str, body: RenameBody) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "El nombre no puede estar vacio.")
    if (meta := storage.rename(model_id, name[:60])) is None:
        raise HTTPException(404, "Objeto no encontrado.")
    return meta


@app.delete("/api/models/{model_id}", dependencies=guard)
def delete_model(model_id: str) -> dict:
    if not storage.delete(model_id):
        raise HTTPException(404, "Objeto no encontrado.")
    return {"deleted": model_id}


# Sin dependencies=guard: ni el visor 3D ni las miniaturas pueden mandar
# cabeceras. Protege el identificador aleatorio, que no se puede listar.
@app.get("/files/{model_id}/{filename}")
def serve_file(model_id: str, filename: str) -> FileResponse:
    """Sirve el .glb, la miniatura y el video del objeto."""
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(404, "Fichero no encontrado.")
    target = storage.file_path(model_id, filename)
    if target is None or not target.is_file():
        raise HTTPException(404, "Fichero no encontrado.")
    return FileResponse(target)


def _banner() -> None:
    ip = lan_ip()
    print("\n" + "=" * 58)
    print("  Foto3D listo")
    print(f"  En este PC       http://localhost:{config.PORT}")
    print(f"  Desde el movil   http://{ip}:{config.PORT}")
    print(f"  Motores          {', '.join(config.PROVIDER_ORDER)}")
    print(f"  Nombres con IA   {'si' if config.HF_TOKEN else 'no (anade HF_TOKEN al .env)'}")
    galeria = f"repo privado {config.HF_DATASET}" if config.STORAGE == "hf" else "disco local"
    print(f"  Galeria          {galeria}")
    print("=" * 58 + "\n")
