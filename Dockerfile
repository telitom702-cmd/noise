FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TORCH_HOME=/opt/torch

WORKDIR /app

# FFmpeg + libsndfile (audio I/O) + gcc (some wheels, e.g. lameenc, may need to build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    ca-certificates \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch (the default wheel pulls ~2 GB of CUDA libraries)
RUN python -m pip install --upgrade pip \
    && pip install torch==2.0.1 torchaudio==2.0.2 \
       --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

# Download the AI model at build time so the first user request isn't slow
RUN python -c "from demucs.pretrained import get_model; get_model('htdemucs')"

COPY . .

# Run as a non-root user
RUN useradd -m appuser && chown -R appuser /app /opt/torch
USER appuser

EXPOSE 10000

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health'%os.getenv('PORT','10000'),timeout=3)" || exit 1

CMD ["python", "bot.py"]
