"""Configuracion del backend. Todo tiene valores por defecto sensatos:
el servidor arranca y funciona sin ningun fichero .env."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = DATA_DIR / "models"
UPLOADS_DIR = DATA_DIR / "uploads"


def _load_dotenv() -> None:
    """Mini lector de .env para no depender de python-dotenv."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


_load_dotenv()

for _d in (DATA_DIR, MODELS_DIR, UPLOADS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

HF_TOKEN: str | None = os.environ.get("HF_TOKEN") or None
PORT: int = int(os.environ.get("FOTO3D_PORT", "8000"))

# Donde vive la galeria.
#   local -> carpeta data/models de este PC (por defecto)
#   hf    -> repositorio privado de Hugging Face, para cuando el backend corre
#            en un hosting gratuito, que borra el disco al reiniciarse
STORAGE: str = os.environ.get("FOTO3D_STORAGE", "local").strip().lower()
HF_DATASET: str | None = os.environ.get("FOTO3D_HF_DATASET") or None

# Clave compartida con la app. Vacia = sin proteccion, que esta bien en la red
# de casa. Si publicas el backend en internet PONLA: si no, cualquiera que
# encuentre la URL puede gastar tu cuota de GPU y borrarte la galeria.
API_KEY: str | None = os.environ.get("FOTO3D_API_KEY") or None

# Orden en el que se prueban los motores 3D. El primero que responda, gana.
PROVIDER_ORDER: list[str] = [
    p.strip()
    for p in os.environ.get("FOTO3D_PROVIDERS", "trellis-community,trellis2,hunyuan3d").split(",")
    if p.strip()
]
