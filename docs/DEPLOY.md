# Deploying Egenta

The discovery engine is stdlib-only Python with a per-engagement SQLite warehouse,
so it runs anywhere a Python interpreter or a container runs: Linux, macOS, Windows,
and any cloud. No build step, no third-party Python dependencies for the engine.

## 1. Bare Python (any OS)

Needs Python 3.12+. Works on Linux, macOS and Windows unchanged (CI proves all three).

```
python -m accelerator version
python -m accelerator bench --json           # deterministic, no key, no network
ANTHROPIC_API_KEY=sk-ant-... python -m accelerator bench --real-llm
```

On Windows use `set ANTHROPIC_API_KEY=...` (cmd) or `$env:ANTHROPIC_API_KEY=...`
(PowerShell). The SQLite warehouse uses OS-correct file URIs, so read-only mode works
on Windows too.

## 2. Container (any cloud / any host)

```
docker build -t egenta .
docker run --rm egenta version
docker run --rm -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" egenta bench --json
# or
docker compose run --rm egenta bench --json
```

The image is `python:3.12-slim` + the engine, runs as a non-root user. Push it to any
registry and run it on ECS/Fargate, Cloud Run, Azure Container Apps, Kubernetes, Fly,
Railway, or a plain Docker host. arm64 and amd64 both work (the base image is multi-arch).

## 3. The Anthropic key

Read at runtime, never baked into the image or source:
- **Local dev:** the `pass` vault (`vault get anthropic/api-key`), used automatically.
- **Container / cloud:** the `ANTHROPIC_API_KEY` env var, injected from your platform's
  secrets manager (AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, k8s Secret).

The deterministic benchmark and all tests need no key, so CI and a smoke deploy run
with nothing configured.

## 4. The warehouse

Default is SQLite, one file per engagement: portable, zero-infra, and the right shape
for a one-off discovery sprint. A multi-tenant Postgres backend is the documented scale
target (see the commented service in `docker-compose.yml`); it is not wired yet and is
not claimed as done.

## 5. What CI proves

`discovery-ci.yml` runs the full test suite and benchmark on ubuntu, macOS and Windows,
and builds and runs the container, on every push. Green there means it runs on all three
host OS types and in a container.
