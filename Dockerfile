# ---- brseAI Discord Interpreter Bot ----
# Minimal image for Discord voice bot deployment on Ubuntu.
#
# Build:
#   docker build -t brseai-discord .
#
# Run:
#   docker run --rm \
#     -e DISCORD_BOT_TOKEN="your-token" \
#     -e OPENAI_API_KEY="sk-..." \
#     brseai-discord --voice-channel-id 123456789012345678
#
# With options:
#   docker run --rm \
#     -e DISCORD_BOT_TOKEN="your-token" \
#     -e OPENAI_API_KEY="sk-..." \
#     brseai-discord --voice-channel-id 123 --src ja --tgt vi --no-tts

FROM python:3.12-slim AS base

# libopus0 — only system dependency needed for discord.py voice
# (PyNaCl wheel bundles libsodium; FFmpeg is NOT required)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Default: run Discord bot mode
ENTRYPOINT ["python", "app.py", "--mode", "discord"]
# Pass extra flags via docker run args (e.g. --voice-channel-id)
CMD []
