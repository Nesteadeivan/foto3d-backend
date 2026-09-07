"""Trabajador: pone tu GPU al servicio del backend publico.

Se ejecuta en tu PC y va preguntando al servidor si hay fotos pendientes. Al
haberlas, las genera con ComfyUI + TRELLIS 2 y devuelve el modelo.

La conexion siempre SALE de tu casa, nunca entra: no hay que abrir puertos en
el router, ni montar tuneles, ni tener IP fija, ni exponer el PC a internet.

Necesita en el .env, o como variables de entorno:

    FOTO3D_SERVER=https://foto3d-backend.onrender.com
    FOTO3D_WORKER_KEY=<la misma clave que pusiste en el servidor>

Se arranca con  trabajador.bat  y se deja abierto.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config  # noqa: E402  (carga el .env al importarse)
from app.providers.comfyui import ComfyUILocal  # noqa: E402

SERVIDOR = (os.environ.get("FOTO3D_SERVER") or "").rstrip("/")
CLAVE = config.WORKER_KEY
ID_TRABAJADOR = os.environ.get("FOTO3D_WORKER_ID") or os.environ.get("COMPUTERNAME", "pc")

ESPERA_SIN_TRABAJO = 4      # segundos entre preguntas cuando no hay nada
ESPERA_SIN_SERVIDOR = 15    # si el servidor no responde, no insistir tan rapido

motor = ComfyUILocal()


def cabeceras() -> dict:
    return {"X-Foto3D-Worker": CLAVE or "", "X-Foto3D-Worker-Id": ID_TRABAJADOR}


def comprobar_configuracion() -> None:
    if not SERVIDOR:
        sys.exit("Falta FOTO3D_SERVER (la direccion de tu backend).")
    if not CLAVE:
        sys.exit("Falta FOTO3D_WORKER_KEY (la misma que pusiste en el servidor).")

    try:
        httpx.get(f"{motor.base}/system_stats", timeout=8).raise_for_status()
    except Exception:
        sys.exit(
            f"ComfyUI no responde en {motor.base}.\n"
            "Arrancalo antes con  D:\\IA FOTO\\comfyui\\arrancar.bat"
        )


def procesar(cliente: httpx.Client, job_id: str) -> None:
    print(f"  [{job_id}] recibido", flush=True)

    foto = config.UPLOADS_DIR / f"trabajo_{job_id}.jpg"
    r = cliente.get(f"{SERVIDOR}/api/worker/photo/{job_id}", headers=cabeceras(), timeout=60)
    r.raise_for_status()
    foto.write_bytes(r.content)

    def progreso(texto: str) -> None:
        print(f"  [{job_id}] {texto}", flush=True)
        try:
            cliente.post(f"{SERVIDOR}/api/worker/progress/{job_id}",
                         headers=cabeceras(), json={"stage": texto}, timeout=15)
        except Exception:
            pass  # informar del progreso nunca debe tumbar la generacion

    inicio = time.time()
    try:
        generacion = motor.generate(foto, progreso)
    except Exception as exc:
        print(f"  [{job_id}] FALLO: {exc}", flush=True)
        cliente.post(f"{SERVIDOR}/api/worker/failed/{job_id}",
                     headers=cabeceras(), json={"reason": str(exc)}, timeout=30)
        return

    tam = generacion.glb_path.stat().st_size
    print(f"  [{job_id}] listo en {time.time()-inicio:.0f}s, {tam/1e6:.1f} MB. Subiendo...",
          flush=True)

    with generacion.glb_path.open("rb") as f:
        cliente.post(
            f"{SERVIDOR}/api/worker/result/{job_id}",
            headers=cabeceras(),
            files={"model": ("model.glb", f, "model/gltf-binary")},
            timeout=300,
        ).raise_for_status()
    print(f"  [{job_id}] entregado", flush=True)


def main() -> None:
    comprobar_configuracion()
    print("=" * 58)
    print("  Trabajador Foto3D")
    print(f"  Servidor : {SERVIDOR}")
    print(f"  ComfyUI  : {motor.base}")
    print(f"  Calidad  : {config.QUALITY}")
    print("  Dejalo abierto. Ctrl+C para parar.")
    print("=" * 58, flush=True)

    sin_trabajo = 0
    with httpx.Client(timeout=httpx.Timeout(30.0)) as cliente:
        while True:
            try:
                r = cliente.post(f"{SERVIDOR}/api/worker/claim", headers=cabeceras())
                if r.status_code == 401:
                    sys.exit("El servidor rechaza la clave (FOTO3D_WORKER_KEY).")
                r.raise_for_status()
                trabajo = r.json()
            except Exception as exc:
                print(f"  sin contacto con el servidor: {str(exc)[:120]}", flush=True)
                time.sleep(ESPERA_SIN_SERVIDOR)
                continue

            if not trabajo.get("job_id"):
                sin_trabajo += 1
                if sin_trabajo % 15 == 1:
                    print("  esperando fotos...", flush=True)
                time.sleep(ESPERA_SIN_TRABAJO)
                continue

            sin_trabajo = 0
            try:
                procesar(cliente, trabajo["job_id"])
            except Exception as exc:
                print(f"  error inesperado: {exc}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Trabajador parado.")
