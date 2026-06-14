# Egenta discovery accelerator. The engine is stdlib-only, so the image is tiny and
# runs on any cloud or host that runs a container (Linux/amd64+arm64, and via Docker
# Desktop on macOS and Windows). The Anthropic key is injected at runtime via the
# ANTHROPIC_API_KEY env var (the pass vault is the local-dev convenience; in a
# container, supply the key from your platform's secrets manager). No build step,
# no third-party Python dependencies.
FROM python:3.12-slim

WORKDIR /app
COPY accelerator/ ./accelerator/
COPY bench/ ./bench/
COPY observer/redactor.py ./observer/redactor.py

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# run as a non-root user
RUN useradd --create-home --uid 10001 egenta && chown -R egenta /app
USER egenta

ENTRYPOINT ["python", "-m", "accelerator"]
CMD ["version"]
