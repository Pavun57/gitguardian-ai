# Deployment

## Local / dev (Docker Compose)

```bash
cd infrastructure/docker
docker compose up -d postgres redis
docker compose --profile tunnel up --build api worker dashboard smee
```

- API: http://localhost:8000 (`/healthz`, `/readyz`, `/docs`)
- Dashboard: http://localhost:3000
- Webhooks reach the API through the smee tunnel (set `SMEE_CHANNEL_URL`).

## CI (GitHub Actions)

`.github/workflows/ci.yml` on every push/PR:

1. **lint** — ruff check + format
2. **test** — unit + mocked integration against service Postgres/Redis
3. **scan-evals** — dogfooding: our own detection eval must stay 100%/0 FPs,
   plus the real-container scanner tests
4. **dashboard** — Next.js production build
5. **docker** — both images build

## Production (Azure Container Apps)

`.github/workflows/deploy.yml` builds images → GHCR → `az containerapp update`.

One-time Azure setup:

```bash
az group create -n gitguardian-rg -l eastus
az containerapp env create -n gitguardian-env -g gitguardian-rg -l eastus

# API (webhook ingress, external)
az containerapp create -n gitguardian-api -g gitguardian-rg \
  --environment gitguardian-env \
  --image ghcr.io/<you>/gitguardian-ai/api:latest \
  --target-port 8000 --ingress external \
  --env-vars <from .env> --secrets <github key, db url, ...>

# Worker (no ingress, mounts nothing — ACA jobs alternative: run as a
# container app with scale rule on Redis queue length)
az containerapp create -n gitguardian-worker -g gitguardian-rg \
  --environment gitguardian-env \
  --image ghcr.io/<you>/gitguardian-ai/api:latest \
  --command "arq" "agents.worker.WorkerSettings"

# Dashboard (external ingress)
az containerapp create -n gitguardian-dashboard -g gitguardian-rg \
  --environment gitguardian-env \
  --image ghcr.io/<you>/gitguardian-ai/dashboard:latest \
  --target-port 3000 --ingress external
```

Data plane: Azure Database for PostgreSQL + Azure Cache for Redis. Point
`DATABASE_URL` / `REDIS_URL` at them. Set the GitHub App webhook URL to the
API's FQDN (`/webhooks/github`) — no smee in production.

### Production caveats (by design, documented in ADR-0002)

- The worker spawns sibling containers via the Docker socket — Azure Container
  Apps cannot do this. For production test isolation, move scanner/test
  execution to a dedicated runner (a VM scale set, or ACA Jobs with a custom
  runner image) behind the Redis queue. The `security/runners/docker_base.py`
  interface is the single seam to reimplement.
- `MASTER_ENCRYPTION_KEY` and the GitHub App private key belong in Azure Key
  Vault, referenced as container app secrets.
