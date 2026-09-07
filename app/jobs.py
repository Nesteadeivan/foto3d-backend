"""Cola de trabajos.

Generar un 3D tarda minutos, asi que el movil sube la foto, recibe un id y va
preguntando el estado. Hay dos formas de que ese trabajo se resuelva:

1. Un **trabajador** lo reclama. Es un PC con GPU (ver `worker.py`) que se
   conecta hacia aqui y pregunta si hay algo pendiente. No hace falta abrirle
   ningun puerto ni exponerlo a internet.
2. Si en `WORKER_WAIT` segundos nadie lo reclama, el propio servidor lo genera
   con los motores de la nube. Asi, si el PC esta apagado, nadie se queda
   tirado: simplemente sale con la calidad del Space gratuito.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import config, naming, storage
from .providers import ALL as PROVIDERS
from .providers.base import Generation, QuotaExceeded


@dataclass
class Job:
    id: str
    user: str = "anon"
    status: str = "queued"          # queued | running | done | error
    stage: str = "En cola..."
    created_at: float = field(default_factory=time.time)
    model: dict | None = None
    error: str | None = None
    error_kind: str | None = None   # quota | unavailable | other
    retry_after: str | None = None
    provider: str | None = None

    # Internos: no se envian al movil.
    image_path: Path | None = None
    fallback_name: str = "Objeto"
    claimed_by: str | None = None

    def public(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "stage": self.stage,
            "model": self.model,
            "error": self.error,
            "error_kind": self.error_kind,
            "retry_after": self.retry_after,
            "provider": self.provider,
        }


_jobs: dict[str, Job] = {}
_pendientes: list[str] = []      # ids esperando a que un trabajador los coja
_lock = threading.Lock()
# Un trabajo a la vez en el propio servidor: la GPU gratuita se serializa igual.
_pool = ThreadPoolExecutor(max_workers=1)


def _set(job_id: str, **campos) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            for k, v in campos.items():
                setattr(job, k, v)


def _en_la_nube():
    """Motores que puede usar el propio servidor, sin contar el local."""
    return [PROVIDERS[n] for n in config.PROVIDER_ORDER
            if n in PROVIDERS and n != "comfyui"]


# --------------------------------------------------------------- respaldo


def _generar_aqui(job_id: str) -> None:
    """Respaldo: nadie reclamo el trabajo, lo hace el propio servidor."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.status != "queued" or job.claimed_by:
            return  # ya lo cogio un trabajador
        _pendientes.remove(job_id) if job_id in _pendientes else None
        job.status = "running"

    imagen, nombre_alt, usuario = job.image_path, job.fallback_name, job.user
    progreso = lambda t: _set(job_id, stage=t)
    ultimo: Exception | None = None

    for provider in _en_la_nube():
        try:
            _set(job_id, provider=provider.label)
            generacion = provider.generate(imagen, progreso)
        except QuotaExceeded as exc:
            _set(job_id, status="error", error_kind="quota", retry_after=exc.retry_after,
                 error=str(exc), stage="Cuota agotada")
            return
        except Exception as exc:
            ultimo = exc
            continue
        _guardar(job_id, generacion, imagen, nombre_alt, usuario)
        return

    _set(job_id, status="error", error_kind="unavailable", stage="Sin motores disponibles",
         error=f"Ningun motor 3D respondio. Ultimo fallo: {ultimo}")


def _guardar(job_id: str, generacion: Generation, imagen: Path | None,
             nombre_alt: str, usuario: str) -> None:
    _set(job_id, stage="Reconociendo el objeto...")
    nombre = (naming.guess_name(imagen) if imagen else None) or nombre_alt
    _set(job_id, stage="Guardando en tu galeria...")
    meta = storage.save(generacion, nombre, source_image=imagen, user=usuario)
    _set(job_id, status="done", stage="Listo", model=meta)


# ------------------------------------------------------------------ publico


def submit(image_path: Path, fallback_name: str, user: str = "anon") -> Job:
    job = Job(id=uuid.uuid4().hex[:12], user=user,
              image_path=image_path, fallback_name=fallback_name)
    with _lock:
        _jobs[job.id] = job
        _pendientes.append(job.id)

    def esperar_y_respaldar() -> None:
        time.sleep(config.WORKER_WAIT)
        _generar_aqui(job.id)

    _pool.submit(esperar_y_respaldar)
    return job


def get(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return job.public() if job else None


# ------------------------------------------------------- lado del trabajador


def claim(worker_id: str) -> dict | None:
    """Entrega el trabajo pendiente mas antiguo, si lo hay."""
    with _lock:
        while _pendientes:
            job = _jobs.get(_pendientes.pop(0))
            if job and job.status == "queued":
                job.status = "running"
                job.claimed_by = worker_id
                job.stage = "Generando en la GPU..."
                job.provider = "TRELLIS 2 (local)"
                return {"job_id": job.id, "quality": config.QUALITY}
    return None


def worker_image(job_id: str) -> Path | None:
    with _lock:
        job = _jobs.get(job_id)
        return job.image_path if job and job.claimed_by else None


def worker_progress(job_id: str, stage: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or not job.claimed_by:
            return False
        job.stage = stage
        return True


def worker_done(job_id: str, glb: Path) -> dict | None:
    """El trabajador ha terminado y nos ha subido el .glb."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None or not job.claimed_by:
            return None
        imagen, nombre_alt, usuario = job.image_path, job.fallback_name, job.user

    _guardar(job_id, Generation(glb_path=glb, provider="comfyui"), imagen, nombre_alt, usuario)
    return get(job_id)


def worker_failed(job_id: str, motivo: str) -> None:
    """Si el trabajador falla, lo intenta el servidor con los motores de nube."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.claimed_by = None
        job.status = "queued"
        job.stage = "La GPU fallo, probando en la nube..."
        job.error = motivo[:300]
    _pool.submit(_generar_aqui, job_id)
