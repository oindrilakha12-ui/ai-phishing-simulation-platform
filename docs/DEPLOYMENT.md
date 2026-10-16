# Deployment guide

> **Status: UNTESTED.** These steps are written from the platforms' documented workflows and the
> project's Dockerfiles. None of them were executed for this build. Only local Windows
> (SQLite, demo mode) was verified.

## Common requirements

- Two containers: `backend/Dockerfile` (port 8001; it runs `alembic upgrade head`, then the idempotent
  seed, then uvicorn) and `frontend/Dockerfile` (port 3000; Next.js standalone).
- A managed PostgreSQL database.
- Required environment variables: `DATABASE_URL`, `JWT_SECRET` (≥32 random chars), `ENVIRONMENT=production`,
  `COOKIE_SECURE=true`, `FRONTEND_ORIGIN=https://<frontend-host>` and `OIDC_MOCK_ENABLED=false`.
  Optional: `AI_PROVIDER` and its key.
- The frontend image needs the build argument `BACKEND_URL=https://<backend-host>`. Next.js rewrites are
  resolved at build time, so set it when building.
- **Remove or replace the demo seed for real tenants.** `python -m app.seed` creates demo accounts with a
  published password. For production, change the backend `CMD` to run only migrations and uvicorn.
- `/metrics` should not be public. Restrict it with ingress rules or a private network.

## Render (Blueprint)

1. Create a **PostgreSQL** instance and copy its internal connection string. Convert
   `postgres://` to `postgresql+psycopg://`.
2. Create a **Web Service** from `backend/` (Docker). Set the environment variables above and the health
   check path `/health/ready`.
3. Create a **Web Service** from `frontend/` (Docker) with the build argument `BACKEND_URL` set to the
   backend's URL.
4. Set `FRONTEND_ORIGIN` on the backend to the frontend URL, then redeploy.

## Railway

1. Create a new project, then add PostgreSQL.
2. Add a service from the repo with root `backend`. Railway detects the Dockerfile. Set the variables, and
   reference `${{Postgres.DATABASE_URL}}` (adjust the scheme to `postgresql+psycopg://`).
3. Add a service with root `frontend` and the build variable `BACKEND_URL`.
4. Generate domains for both services.

## Azure Container Apps

```bash
az group create -n phishguard-rg -l centralindia
az postgres flexible-server create -g phishguard-rg -n phishguard-pg --tier Burstable --sku-name Standard_B1ms
az acr create -g phishguard-rg -n phishguardacr --sku Basic
az acr build -r phishguardacr -t backend:1 ./backend
az acr build -r phishguardacr -t frontend:1 --build-arg BACKEND_URL=https://<backend-fqdn> ./frontend
az containerapp env create -g phishguard-rg -n phishguard-env -l centralindia
az containerapp create -g phishguard-rg -n backend --environment phishguard-env \
  --image phishguardacr.azurecr.io/backend:1 --target-port 8001 --ingress external \
  --secrets jwt=<secret> db=<postgresql+psycopg://...> \
  --env-vars JWT_SECRET=secretref:jwt DATABASE_URL=secretref:db ENVIRONMENT=production COOKIE_SECURE=true
az containerapp create -g phishguard-rg -n frontend --environment phishguard-env \
  --image phishguardacr.azurecr.io/frontend:1 --target-port 3000 --ingress external
```

Store secrets in **Key Vault** and reference them from Container Apps for real use.
