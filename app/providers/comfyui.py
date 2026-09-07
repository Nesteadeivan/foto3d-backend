"""Motor local: TRELLIS 2 corriendo en tu propia GPU a traves de ComfyUI.

Es el unico camino que da a la vez gratis, ilimitado y buena calidad: no hay
cuotas ni colas de terceros, y la malla sale con mucho mas detalle que la de
los Spaces publicos. A cambio, el PC tiene que estar encendido.

ComfyUI trabaja con grafos de nodos. En `workflows/trellis2_api.json` esta la
plantilla oficial de ComfyUI ya convertida a formato API; aqui solo se le
cambian la foto, la semilla y los ajustes de calidad antes de encolarla.
"""
from __future__ import annotations

import json
import random
import time
import uuid
from pathlib import Path

import httpx

from .. import config
from .base import Generation, ProgressFn, ProviderUnavailable

# Identificadores de los nodos dentro de la plantilla. Si algun dia se cambia
# la plantilla por otra, esto es lo unico que hay que revisar.
NODO_IMAGEN = "122"        # LoadImage
NODO_TRELLIS2 = "316"      # PrimitiveBoolean: usar TRELLIS 2 en vez de Pixal3D
NODO_TEXTURA = "288"       # PrimitiveInt: resolucion de la textura
NODO_UPSAMPLE = "94"       # Trellis2UpsampleStage
NODO_REMALLADO = "241"     # RemeshMesh
NODO_DECIMADO = "186"      # DecimateMesh
NODO_GUARDAR = "322"       # Save3DAdvanced

# Mas resolucion y mas caras = mas detalle y mas minutos. Medido en una
# RTX 4070: equilibrada ronda los 4 minutos y 12 MB por objeto.
#
# Ojo con los limites que impone ComfyUI, o el grafo no pasa la validacion y
# se genera para nada: upsample es un entero entre 1024 y 2048 (no vale 768),
# y remesh va de 32 a 2048.
CALIDADES = {
    "rapida": {"upsample": 1024, "remesh": 320, "caras": 120000, "textura": 1024},
    "equilibrada": {"upsample": 1024, "remesh": 512, "caras": 250000, "textura": 2048},
    "alta": {"upsample": 1536, "remesh": 768, "caras": 500000, "textura": 4096},
}


class ComfyUILocal:
    name = "comfyui"
    label = "TRELLIS 2 (local)"

    def __init__(self) -> None:
        self.base = config.COMFY_URL.rstrip("/")
        self.plantilla = Path(__file__).resolve().parent.parent / "workflows" / "trellis2_api.json"

    # ---------------------------------------------------------------- helpers

    def _cliente(self) -> httpx.Client:
        return httpx.Client(base_url=self.base, timeout=httpx.Timeout(60.0, read=120.0))

    def _subir_imagen(self, client: httpx.Client, image_path: Path) -> str:
        archivos = {"image": (image_path.name, image_path.read_bytes(), "image/png")}
        r = client.post("/upload/image", files=archivos, data={"overwrite": "true"})
        r.raise_for_status()
        return r.json()["name"]

    def _preparar_grafo(self, nombre_imagen: str) -> dict:
        grafo = json.loads(self.plantilla.read_text(encoding="utf-8"))
        q = CALIDADES.get(config.QUALITY, CALIDADES["equilibrada"])

        grafo[NODO_IMAGEN]["inputs"]["image"] = nombre_imagen
        grafo[NODO_TRELLIS2]["inputs"]["value"] = True
        grafo[NODO_TEXTURA]["inputs"]["value"] = q["textura"]
        grafo[NODO_UPSAMPLE]["inputs"]["target_resolution"] = q["upsample"]
        grafo[NODO_REMALLADO]["inputs"]["resolution"] = q["remesh"]
        grafo[NODO_DECIMADO]["inputs"]["target_face_count"] = q["caras"]

        # Sin semilla nueva, ComfyUI devuelve el resultado cacheado de la
        # ejecucion anterior en lugar de generar de nuevo.
        for nodo in grafo.values():
            entradas = nodo.get("inputs", {})
            if "seed" in entradas and not isinstance(entradas["seed"], list):
                entradas["seed"] = random.randint(0, 2**31 - 1)
        return grafo

    def _glb_del_resultado(self, historial: dict) -> Path | None:
        """Busca el .glb entre las salidas y lo localiza en el disco."""
        salidas = historial.get("outputs", {})
        nombres: list[str] = []
        for nodo in (NODO_GUARDAR, *salidas):
            for valores in salidas.get(nodo, {}).values():
                for v in valores if isinstance(valores, list) else []:
                    if isinstance(v, str) and v.endswith(".glb"):
                        nombres.append(v)
                    elif isinstance(v, dict) and str(v.get("filename", "")).endswith(".glb"):
                        nombres.append(v["filename"])

        for nombre in nombres:
            for raiz in (config.COMFY_OUTPUT, config.COMFY_OUTPUT / "3d"):
                candidato = raiz / Path(nombre).name
                if candidato.is_file():
                    return candidato
        return None

    # ----------------------------------------------------------------- publico

    def generate(self, image_path: Path, progress: ProgressFn) -> Generation:
        progress("Conectando con tu GPU...")
        try:
            with self._cliente() as client:
                client.get("/system_stats").raise_for_status()

                progress("Enviando la foto...")
                nombre = self._subir_imagen(client, image_path)

                grafo = self._preparar_grafo(nombre)
                r = client.post("/prompt", json={"prompt": grafo, "client_id": uuid.uuid4().hex})
                if r.status_code != 200:
                    raise ProviderUnavailable(f"ComfyUI rechazo el trabajo: {r.text[:300]}")

                respuesta = r.json()
                # ComfyUI acepta el trabajo con 200 aunque haya nodos invalidos:
                # simplemente los ignora. Si el que ignora es el que guarda el
                # modelo, generariamos minutos para nada. Mejor fallar aqui.
                if errores := respuesta.get("node_errors"):
                    detalle = json.dumps(errores, ensure_ascii=False)[:400]
                    raise ProviderUnavailable(f"El flujo tiene nodos invalidos: {detalle}")
                prompt_id = respuesta["prompt_id"]

                inicio = time.time()
                while time.time() - inicio < config.COMFY_TIMEOUT:
                    historial = client.get(f"/history/{prompt_id}").json()
                    if prompt_id in historial:
                        entrada = historial[prompt_id]
                        estado = entrada.get("status", {}).get("status_str")
                        if estado == "error":
                            detalle = json.dumps(entrada.get("status", {}))[:400]
                            raise ProviderUnavailable(f"ComfyUI fallo: {detalle}")

                        progress("Guardando el modelo...")
                        glb = self._glb_del_resultado(entrada)
                        if glb is None:
                            raise ProviderUnavailable("ComfyUI termino pero no encuentro el .glb.")
                        return Generation(glb_path=glb, provider=self.name)

                    transcurrido = int(time.time() - inicio)
                    progress(f"Generando en tu GPU... {transcurrido // 60}:{transcurrido % 60:02d}")
                    time.sleep(3)

                raise ProviderUnavailable("ComfyUI ha tardado demasiado.")

        except ProviderUnavailable:
            raise
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                f"No hay conexion con ComfyUI en {self.base}. Comprueba que esta arrancado. ({exc})"
            ) from exc
