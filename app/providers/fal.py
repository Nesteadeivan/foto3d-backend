"""Motor de pago: Hunyuan3D v3 a traves de fal.ai.

Es el camino sin instalar nada y sin cuotas: se paga por modelo generado
(del orden de 0,15 a 0,40 euros segun los ajustes). A cambio no hace falta
tener el PC encendido ni esperar turnos.

Hunyuan3D v3 admite ademas fotos de otros angulos (trasera, izquierda y
derecha). Es, con diferencia, lo que mas mejora el resultado: con una sola
foto el modelo se inventa la parte que no ve, y con cuatro deja de hacerlo.
"""
from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path

import httpx

from .. import config
from .base import Generation, ProgressFn, ProviderUnavailable, QuotaExceeded

MODELO = "fal-ai/hunyuan3d-v3/image-to-3d"
COLA = f"https://queue.fal.run/{MODELO}"

# face_count va de 40.000 a 1.500.000. Mas caras = mas detalle y mas peso.
# PBR anade tres texturas (color, metalico y normales): se ve mejor, pero
# triplica el tamano del fichero.
#
# Medido: 500.000 caras con PBR dan 35 MB, que es inviable de descargar en un
# movil con datos. Por eso el equilibrio por defecto renuncia al PBR.
CALIDADES = {
    "rapida": {"face_count": 100_000, "enable_pbr": False},       # ~3 MB
    "equilibrada": {"face_count": 250_000, "enable_pbr": False},  # ~8 MB
    "alta": {"face_count": 500_000, "enable_pbr": True},          # ~35 MB
}


def _data_uri(ruta: Path) -> str:
    """fal.ai acepta la imagen incrustada, asi nos ahorramos subirla aparte."""
    tipo = mimetypes.guess_type(ruta.name)[0] or "image/jpeg"
    return f"data:{tipo};base64," + base64.b64encode(ruta.read_bytes()).decode("ascii")


class FalHunyuan3D:
    name = "fal"
    label = "Hunyuan3D v3 (fal.ai)"

    def generate(self, image_path: Path, progress: ProgressFn) -> Generation:
        if not config.FAL_KEY:
            raise ProviderUnavailable(
                "Falta FAL_KEY. Sacala en https://fal.ai/dashboard/keys y ponla en el .env."
            )

        q = CALIDADES.get(config.QUALITY, CALIDADES["equilibrada"])
        cabeceras = {"Authorization": f"Key {config.FAL_KEY}"}
        cuerpo = {
            "input_image_url": _data_uri(image_path),
            "generate_type": "Normal",   # con textura; Geometry seria solo malla
            "polygon_type": "triangle",
            **q,
        }

        with httpx.Client(timeout=httpx.Timeout(120.0, read=180.0)) as client:
            progress("Enviando la foto a fal.ai...")
            r = client.post(COLA, headers=cabeceras, json=cuerpo)
            if r.status_code in (401, 403):
                raise ProviderUnavailable("fal.ai rechaza la clave (FAL_KEY).")
            if r.status_code in (402, 429):
                # Saldo agotado o limite de peticiones: no sirve reintentar ya.
                raise QuotaExceeded("fal.ai: sin saldo o demasiadas peticiones.")
            if r.status_code >= 400:
                raise ProviderUnavailable(f"fal.ai devolvio {r.status_code}: {r.text[:250]}")

            envio = r.json()
            url_estado = envio.get("status_url")
            url_resultado = envio.get("response_url")
            if not url_estado or not url_resultado:
                raise ProviderUnavailable(f"Respuesta inesperada de fal.ai: {str(envio)[:250]}")

            inicio = time.time()
            while time.time() - inicio < 900:
                estado = client.get(url_estado, headers=cabeceras).json()
                situacion = estado.get("status")
                if situacion == "COMPLETED":
                    break
                if situacion in ("FAILED", "CANCELLED"):
                    raise ProviderUnavailable(f"fal.ai fallo: {str(estado)[:250]}")

                transcurrido = int(time.time() - inicio)
                cola = estado.get("queue_position")
                if cola:
                    progress(f"En cola en fal.ai (puesto {cola})...")
                else:
                    progress(f"Generando en fal.ai... {transcurrido // 60}:{transcurrido % 60:02d}")
                time.sleep(3)
            else:
                raise ProviderUnavailable("fal.ai ha tardado demasiado.")

            progress("Descargando el modelo...")
            resultado = client.get(url_resultado, headers=cabeceras).json()
            enlace = (resultado.get("model_glb") or {}).get("url")
            if not enlace:
                enlace = (resultado.get("model_urls") or {}).get("glb")
            if not enlace:
                raise ProviderUnavailable(f"fal.ai no devolvio ningun GLB: {str(resultado)[:250]}")

            destino = config.UPLOADS_DIR / f"fal_{int(time.time())}.glb"
            with client.stream("GET", enlace) as flujo:
                flujo.raise_for_status()
                with destino.open("wb") as f:
                    for trozo in flujo.iter_bytes():
                        f.write(trozo)

            # La miniatura que devuelve fal viene bien y sale gratis.
            miniatura = None
            if url_thumb := (resultado.get("thumbnail") or {}).get("url"):
                try:
                    img = client.get(url_thumb)
                    img.raise_for_status()
                    miniatura = config.UPLOADS_DIR / f"fal_{int(time.time())}.png"
                    miniatura.write_bytes(img.content)
                except Exception:
                    miniatura = None

        return Generation(glb_path=destino, cutout_path=miniatura, provider=self.name)
