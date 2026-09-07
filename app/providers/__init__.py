"""Registro de motores 3D disponibles.

Se eligen y ordenan con FOTO3D_PROVIDERS. Por ejemplo:
    FOTO3D_PROVIDERS=fal                       solo fal.ai (de pago, mejor calidad)
    FOTO3D_PROVIDERS=comfyui                   solo tu GPU (gratis, mas lento)
    FOTO3D_PROVIDERS=fal,trellis-community     fal.ai y, si falla, el Space gratuito
"""
from .comfyui import ComfyUILocal
from .fal import FalHunyuan3D
from .hf_space import ALL as _EN_LA_NUBE

_local = ComfyUILocal()
_fal = FalHunyuan3D()

ALL = {**_EN_LA_NUBE, _local.name: _local, _fal.name: _fal}
