# Imagen del backend. Sirve para cualquier hosting: el puerto se toma de la
# variable PORT que inyecta la plataforma (Render, Koyeb, Fly...), y si no
# existe se usa el 8000 de siempre.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY --chown=user app ./app

# En la nube el disco es efimero: la galeria va al repositorio privado.
ENV FOTO3D_STORAGE=hf

# Forma shell a proposito, para que se expanda ${PORT}.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
