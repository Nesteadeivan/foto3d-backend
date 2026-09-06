"""Contrato comun de los motores de generacion 3D.

Anadir un motor nuevo (TRELLIS local en tu RTX 4070, fal.ai, Tripo...) es
implementar `Provider.generate` y registrarlo en `providers/__init__` -- el
resto de la app no cambia.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

ProgressFn = Callable[[str], None]


@dataclass
class Generation:
    """Lo que devuelve un motor tras generar el 3D."""

    glb_path: Path
    cutout_path: Path | None = None      # foto con el fondo quitado -> miniatura
    preview_video: Path | None = None    # video giratorio del objeto
    provider: str = ""


class QuotaExceeded(RuntimeError):
    """La cuota gratuita de GPU se ha agotado. No tiene sentido reintentar ya."""

    def __init__(self, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailable(RuntimeError):
    """El motor esta caido, saturado o ha fallado. Se puede probar el siguiente."""


class Provider(Protocol):
    name: str
    label: str

    def generate(self, image_path: Path, progress: ProgressFn) -> Generation: ...
