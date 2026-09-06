"""Cola de trabajos: generar un 3D tarda entre 25 s y varios minutos, asi que
el movil no espera con la peticion abierta. Sube la foto, recibe un id y va
preguntando el estado, con lo que puede mostrar el progreso paso a paso.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, naming, storage
from .providers.base import QuotaExceeded
from .providers.hf_space import ALL as PROVIDERS


@dataclass
class Job:
    id: str
    status: str = "queued"          # queued | running | done | error
    stage: str = "En cola..."
    created_at: float = field(default_factory=time.time)
    model: dict | None = None
    error: str | None = None
    error_kind: str | None = None   # quota | unavailable | other
    retry_after: str | None = None
    provider: str | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
# Un solo trabajo a la vez: la GPU gratuita se serializa igualmente y asi no
# se gasta la cuota en dos generaciones simultaneas.
_pool = ThreadPoolExecutor(max_workers=1)


def _set(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            for key, value in fields.items():
                setattr(job, key, value)


def _active_providers():
    return [PROVIDERS[n] for n in config.PROVIDER_ORDER if n in PROVIDERS]


def _run(job_id: str, image_path: Path, fallback_name: str) -> None:
    _set(job_id, status="running", stage="Preparando la foto...")
    progress = lambda text: _set(job_id, stage=text)

    last_error: Exception | None = None
    for provider in _active_providers():
        try:
            _set(job_id, provider=provider.label)
            generation = provider.generate(image_path, progress)
        except QuotaExceeded as exc:
            # La cuota es compartida por todos los Spaces: no sirve reintentar.
            _set(job_id, status="error", error_kind="quota", retry_after=exc.retry_after,
                 error=str(exc), stage="Cuota agotada")
            return
        except Exception as exc:
            last_error = exc
            continue  # siguiente motor de la cadena

        progress("Reconociendo el objeto...")
        name = naming.guess_name(image_path) or fallback_name

        progress("Guardando en tu galeria...")
        meta = storage.save(generation, name, source_image=image_path)
        _set(job_id, status="done", stage="Listo", model=meta)
        return

    _set(job_id, status="error", error_kind="unavailable", stage="Sin motores disponibles",
         error=f"Ningun motor 3D respondio. Ultimo fallo: {last_error}")


def submit(image_path: Path, fallback_name: str) -> Job:
    job = Job(id=uuid.uuid4().hex[:12])
    with _lock:
        _jobs[job.id] = job
    _pool.submit(_run, job.id, image_path, fallback_name)
    return job


def get(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return asdict(job) if job else None
