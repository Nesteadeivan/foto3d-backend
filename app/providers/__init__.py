"""Registro de motores 3D disponibles.

Se eligen y ordenan con FOTO3D_PROVIDERS. Por ejemplo:
    FOTO3D_PROVIDERS=comfyui                        solo tu GPU
    FOTO3D_PROVIDERS=comfyui,trellis-community      tu GPU y, si esta apagada,
                                                    el Space gratuito
"""
from .comfyui import ComfyUILocal
from .hf_space import ALL as _EN_LA_NUBE

_local = ComfyUILocal()

ALL = {**_EN_LA_NUBE, _local.name: _local}
