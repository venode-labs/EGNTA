# Deploying EGNTA

The engine is stdlib-only Python with a per-engagement SQLite warehouse, so it runs
anywhere a Python interpreter or a container runs: Linux, macOS, Windows, any cloud. No
build step, no third-party Python dependencies.

## Bare Python

Needs Python 3.12 or newer. The same commands work on Linux, macOS and Windows.

```
python -m accelerator version
python -m accelerator bench --json           # deterministic, no key, no network
ANTHROPIC_API_KEY=sk-ant-... python -m accelerator bench --real-llm
```

On Windows set the key with `set ANTHROPIC_API_KEY=...` in cmd or
`$env:ANTHROPIC_API_KEY=...` in PowerShell. The SQLite warehouse builds OS-correct file
URIs, so read-only mode works on Windows as well.

## Container

```
docker build -t egnta .
docker run --rm egnta version
docker run --rm -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" egnta bench --json
docker compose run --rm egnta bench --json
```

The image is `python:3.12-slim` plus the engine and runs as a non-root user. Push it to
any registry and run it on ECS or Fargate, Cloud Run, Azure Container Apps, Kubernetes,
Fly or Railway, or a plain Docker host. Both arm64 and amd64 work; the base image is
multi-arch.

## The Anthropic key

The key is read at runtime, never baked into the image or source. Local development reads
it from the `pass` vault. A container reads `ANTHROPIC_API_KEY`, which you inject from your
platform secrets manager: AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, or a
Kubernetes Secret. The deterministic benchmark and the tests need no key, so CI and a
smoke deploy run with nothing configured.

## The warehouse

SQLite, one file per engagement: portable, no infrastructure, and the right shape for a
one-off discovery sprint. A multi-tenant Postgres backend is the scale target, sketched
in the commented service in `docker-compose.yml` and not yet wired.

## Continuous integration

`discovery-ci.yml` runs the test suite and the benchmark on Ubuntu, macOS and Windows and
builds and runs the container on every push, so a green build means it works on all three
host operating systems and in a container.
