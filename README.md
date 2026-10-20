# Docker Compose Service Lab

A self-contained demonstration of Docker Compose, health checks, service-level Dockerfiles and smoke tests for three FastAPI services and a Go API. Includes the minimal example application source so this repository stands alone.

## Run

Requires Docker Engine/Desktop with Compose plugin.

```bash
docker compose up --build -d
bash smoke.sh
docker compose down
```

The endpoints are expected at localhost ports 8000, 8001, 8002 and 8080. See `compose.yml` for port, volume and healthcheck configuration.

## Tests and limitations

Python services have pytest tests under `services/*-api`. Go tests are in `services/link-api`. Compose execution has not been verified in this environment. All APIs are unauthenticated demo applications; do not expose this Compose stack publicly or store sensitive data in it.
