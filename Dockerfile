# ---- brseAI Realtime Interpreter ----
# Minimal image for running realtime and fallback modes.
#
# Build:
#   docker build -t brseai .
#
# Run realtime mode:
#   docker run --rm \
#     -e OPENAI_API_KEY="sk-..." \
#     brseai --mode realtime --input mic
#
# Run fallback mode:
#   docker run --rm \
#     -e OPENAI_API_KEY="sk-..." \
#     brseai --mode fallback --input-device 1 --seconds 5

FROM python:3.12-slim AS base

# Install PortAudio (required for sounddevice)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       portaudio19-dev \
       gcc \
       libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Default: run realtime mode
ENTRYPOINT ["python", "app.py"]
CMD ["--mode", "realtime", "--input", "mic"]

