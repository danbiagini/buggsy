FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the default voice into the image — no startup download, no volume to manage.
ARG VOICE_BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium
ARG VOICE_NAME=en_US-amy-medium
RUN mkdir -p /voices \
    && curl -fsSL "${VOICE_BASE}/${VOICE_NAME}.onnx" -o "/voices/${VOICE_NAME}.onnx" \
    && curl -fsSL "${VOICE_BASE}/${VOICE_NAME}.onnx.json" -o "/voices/${VOICE_NAME}.onnx.json"

ENV BUGGSY_TTS_DEFAULT_VOICE=en_US-amy-medium
ENV BUGGSY_TTS_VOICES_DIR=/voices

COPY app.py .

EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
