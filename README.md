# Foto3D — backend

Servidor de la app Foto3D: recibe una foto, la manda a un modelo de IA de
reconstrucción 3D y devuelve un `.glb`.

## En tu PC

Doble clic en `run.bat`, o desde PowerShell `.\run.bat`.

La galería se guarda en `data/models/`.

## En la nube (Render, gratis y sin tarjeta)

> **Hugging Face Spaces ya no vale para esto.** Desde 2026 los Spaces con
> cómputo (Docker y Gradio) requieren plan de pago; solo los Static siguen
> siendo gratis, y un Static no puede ejecutar Python.

Render mantiene capa gratuita sin tarjeta. Lo que hay que saber:

- El servicio **se duerme a los 15 minutos** sin uso, y despertar tarda 30-60 s.
  La primera foto del día será lenta; las siguientes, normales.
- El disco es **efímero**: por eso `FOTO3D_STORAGE=hf` manda la galería a un
  repositorio privado de tu cuenta de Hugging Face, que sí es gratis y duradero.
- Necesita el código en un repositorio de GitHub (cuenta gratuita).

### Pasos

1. Sube esta carpeta a un repositorio de GitHub. El `.gitignore` ya excluye
   `.env`, `.venv/` y `data/`.
2. En [render.com](https://render.com) → **New → Web Service** → conecta el
   repositorio → runtime **Docker** → plan **Free**.
3. En **Environment**, añade estas variables:

| Nombre | Valor |
|---|---|
| `HF_TOKEN` | Tu token de Hugging Face, con permiso de **Write** |
| `FOTO3D_HF_DATASET` | `tu-usuario/foto3d-galeria` |
| `FOTO3D_API_KEY` | Una contraseña larga que te inventes |
| `FOTO3D_PROVIDERS` | `trellis-community,hunyuan3d` |
| `FOTO3D_STORAGE` | `hf` |

4. La URL que te dé (`https://foto3d-api.onrender.com`) va en
   `mobile/app.json` → `extra.defaultServerUrl`, y la misma clave del punto 3
   en `extra.apiKey`. Luego ya puedes compilar el APK.

> El token necesita permiso de **Write**, no solo Read: tiene que poder crear
> el repositorio de la galería y subir los modelos.

> `FOTO3D_API_KEY` no es opcional en internet: sin ella, cualquiera que
> encuentre la URL puede gastarte la cuota de GPU y borrarte la galería.

**Nunca** subas el fichero `.env`. El `.gitignore` ya lo excluye.

### Alternativa: tu propio PC con un túnel

Si prefieres no depender de un hosting, deja el backend en tu PC y expónlo con
un túnel (Cloudflare Tunnel o ngrok). Ventajas: la galería se queda en tu disco
(sin token de escritura, sin límites de tamaño) y no hay esperas de arranque.
Pega: el PC tiene que estar encendido.

## Configuración

Todo es opcional y tiene valores por defecto sensatos.

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `HF_TOKEN` | vacío | Multiplica la cuota de GPU y activa los nombres automáticos |
| `FOTO3D_PROVIDERS` | `trellis-community,trellis2,hunyuan3d` | Motores 3D, en orden |
| `FOTO3D_STORAGE` | `local` | `local` (disco) o `hf` (repositorio privado) |
| `FOTO3D_HF_DATASET` | vacío | Repositorio de la galería, si `FOTO3D_STORAGE=hf` |
| `FOTO3D_API_KEY` | vacío | Clave que debe mandar la app. Vacía = sin protección |
| `FOTO3D_PORT` | `8000` | Puerto en local (en la nube manda `PORT`) |

## API

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/health` | Estado, motores activos, modo de galería. Sin clave |
| `POST` | `/api/generate` | Sube la foto (`multipart`, campo `photo`) → `job_id` |
| `GET` | `/api/jobs/{id}` | Progreso y resultado |
| `GET` | `/api/models` | Lista de objetos |
| `PATCH` | `/api/models/{id}` | Renombrar |
| `DELETE` | `/api/models/{id}` | Borrar |
| `GET` | `/files/{id}/model.glb` | Descargar el modelo. Sin clave, id no adivinable |

Documentación interactiva en `/docs`.
