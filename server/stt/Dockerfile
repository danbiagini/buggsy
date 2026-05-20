FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# faster-whisper looks for libcudnn/libcublas via the dynamic linker.
# The pip wheels drop these alongside the site-packages; add their
# lib/ dirs to the loader path so CUDA inference picks them up.
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib

# Defaults — override per-deployment via env. Bigger models give better
# accuracy in noisy rooms at the cost of VRAM and load time:
#   tiny.en   ~40MB    distilled English-only
#   base.en   ~150MB
#   small.en  ~500MB   <- default; loads fast, fine for short commands
#   medium.en ~1.5GB
#   large-v3   ~3GB    full multilingual, best accuracy
ENV BUGGSY_STT_MODEL=small.en
ENV BUGGSY_STT_DEVICE=auto
ENV BUGGSY_STT_COMPUTE_TYPE=default
ENV HF_HOME=/cache/huggingface

COPY app.py .

EXPOSE 8002
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
