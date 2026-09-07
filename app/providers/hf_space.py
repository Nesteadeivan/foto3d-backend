"""Motores 3D que corren en Spaces publicos de Hugging Face (GPU gratis).

Los tres son modelos open source de primer nivel. Se prueban en cadena: si uno
esta caido o saturado, se pasa al siguiente automaticamente.

Aviso sobre la cuota: los Spaces con ZeroGPU dan una cuota de GPU limitada por
dia. Sin token es muy pequena (unas pocas generaciones); con un token gratuito
de Hugging Face se multiplica. TRELLIS comunitario gasta ~25 s por objeto y
TRELLIS.2 reserva 120 s de golpe, por eso el primero va por delante.
"""
from __future__ import annotations

import re
from pathlib import Path

from gradio_client import Client, handle_file
from gradio_client.exceptions import AppError

from .. import config
from .base import Generation, ProgressFn, ProviderUnavailable, QuotaExceeded

_HTTPX = {"timeout": 600.0}

# mesh_simplify es la PROPORCION DE MALLA QUE SE TIRA: 0.95 deja solo el 5% de
# los poligonos, que es lo que trae la demo por defecto y por lo que los
# modelos salian pobres. texture_size va de 512 a 2048.
_QUALITY = {
    "rapida": {"steps": 12, "simplify": 0.95, "texture": 1024},
    "equilibrada": {"steps": 16, "simplify": 0.80, "texture": 2048},
    "alta": {"steps": 25, "simplify": 0.50, "texture": 2048},
}


def _quality() -> dict:
    return _QUALITY.get(config.QUALITY, _QUALITY["alta"])
_QUOTA_RE = re.compile(r"exceeded your (?:zerogpu )?quota|gpu quota|quota exceeded", re.I)
_RETRY_RE = re.compile(r"try again in ([0-9:]+)", re.I)


def _client(space: str) -> Client:
    try:
        return Client(space, token=config.HF_TOKEN, verbose=False, httpx_kwargs=_HTTPX)
    except Exception as exc:  # el Space esta dormido, movido o caido
        raise ProviderUnavailable(f"No se pudo conectar con {space}: {exc}") from exc


def _translate(exc: Exception, space: str) -> Exception:
    """Convierte errores de Gradio en excepciones nuestras con mensaje util."""
    msg = str(exc)
    if isinstance(exc, AppError) and _QUOTA_RE.search(msg):
        retry = _RETRY_RE.search(msg)
        return QuotaExceeded(
            "Se ha agotado la cuota gratuita de GPU de Hugging Face.",
            retry_after=retry.group(1) if retry else None,
        )
    return ProviderUnavailable(f"{space}: {msg}")


def _as_path(value) -> Path | None:
    """Los Spaces devuelven rutas como str o como dict; normalizamos."""
    if isinstance(value, dict):
        value = value.get("path") or value.get("video") or value.get("url")
    if isinstance(value, str) and value and not value.startswith("http"):
        p = Path(value)
        if p.exists():
            return p
    return None


def _pick_glb(items) -> Path | None:
    """De entre varias salidas, quedarse con el .glb mas grande (el texturizado)."""
    best: Path | None = None
    for item in items if isinstance(items, (list, tuple)) else [items]:
        p = _as_path(item)
        if p and p.suffix.lower() in (".glb", ".gltf"):
            if best is None or p.stat().st_size > best.stat().st_size:
                best = p
    return best


class TrellisCommunity:
    """TRELLIS (Microsoft, licencia MIT) servido por la comunidad.

    Motor por defecto: hace imagen -> GLB en una sola llamada, tarda unos 25 s
    y ademas devuelve un video giratorio que usamos como miniatura.
    """

    name = "trellis-community"
    label = "TRELLIS"
    space = "trellis-community/TRELLIS"

    def generate(self, image_path: Path, progress: ProgressFn) -> Generation:
        progress("Conectando con el motor 3D...")
        client = _client(self.space)
        try:
            try:
                client.predict(api_name="/start_session")
            except Exception:
                pass  # algunos despliegues no exponen sesion; no es critico

            progress("Recortando el objeto del fondo...")
            cutout = _as_path(client.predict(image=handle_file(str(image_path)),
                                             api_name="/preprocess_image"))

            q = _quality()
            progress(f"Generando la malla 3D (calidad {config.QUALITY})...")
            result = client.predict(
                image=handle_file(str(cutout or image_path)),
                multiimages=[],
                seed=0,
                ss_guidance_strength=7.5,
                ss_sampling_steps=q["steps"],
                slat_guidance_strength=3.0,
                slat_sampling_steps=q["steps"],
                multiimage_algo="stochastic",
                mesh_simplify=q["simplify"],
                texture_size=q["texture"],
                api_name="/generate_and_extract_glb",
            )
        except Exception as exc:
            raise _translate(exc, self.space) from exc

        glb = _pick_glb(result)
        if not glb:
            raise ProviderUnavailable(f"{self.space} no devolvio ningun GLB.")

        video = next((v for v in (_as_path(r) for r in result)
                      if v and v.suffix.lower() == ".mp4"), None)
        return Generation(glb_path=glb, cutout_path=cutout,
                          preview_video=video, provider=self.name)


class Trellis2:
    """TRELLIS.2 oficial de Microsoft. Mejor calidad, pero reserva 120 s de
    GPU por peticion, asi que agota la cuota gratuita mucho mas rapido."""

    name = "trellis2"
    label = "TRELLIS.2"
    space = "microsoft/TRELLIS.2"

    def generate(self, image_path: Path, progress: ProgressFn) -> Generation:
        progress("Conectando con TRELLIS.2...")
        client = _client(self.space)
        try:
            try:
                client.predict(api_name="/start_session")
            except Exception:
                pass

            progress("Recortando el objeto del fondo...")
            cutout = _as_path(client.predict(input=handle_file(str(image_path)),
                                             api_name="/preprocess_image"))

            progress("Generando la malla 3D...")
            client.predict(
                image=handle_file(str(cutout or image_path)),
                seed=0,
                resolution="1024",
                api_name="/image_to_3d",
            )

            progress("Extrayendo el modelo y las texturas...")
            # extract_glb no recibe la malla: la toma del estado de la sesion,
            # por eso hay que reutilizar el mismo Client de arriba.
            result = client.predict(decimation_target=300000, texture_size=2048,
                                    api_name="/extract_glb")
        except Exception as exc:
            raise _translate(exc, self.space) from exc

        glb = _pick_glb(result)
        if not glb:
            raise ProviderUnavailable(f"{self.space} no devolvio ningun GLB.")
        return Generation(glb_path=glb, cutout_path=cutout, provider=self.name)


class Hunyuan3D:
    """Hunyuan3D 2.1 de Tencent. Trae quitado de fondo incorporado y genera
    materiales PBR. Sirve de red de seguridad si los TRELLIS fallan."""

    name = "hunyuan3d"
    label = "Hunyuan3D 2.1"
    space = "tencent/Hunyuan3D-2.1"

    def generate(self, image_path: Path, progress: ProgressFn) -> Generation:
        progress("Conectando con Hunyuan3D...")
        client = _client(self.space)
        try:
            progress("Generando la malla 3D y las texturas...")
            result = client.predict(
                image=handle_file(str(image_path)),
                steps=30,
                guidance_scale=5.0,
                seed=1234,
                octree_resolution=256,
                check_box_rembg=True,   # quita el fondo el propio Space
                num_chunks=8000,
                randomize_seed=False,
                api_name="/generation_all",
            )
        except Exception as exc:
            raise _translate(exc, self.space) from exc

        glb = _pick_glb(result)
        if not glb:
            raise ProviderUnavailable(f"{self.space} no devolvio ningun GLB.")
        return Generation(glb_path=glb, provider=self.name)


ALL = {p.name: p for p in (TrellisCommunity(), Trellis2(), Hunyuan3D())}
