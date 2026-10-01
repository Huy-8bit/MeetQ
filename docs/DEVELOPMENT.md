# Development And Deploy Commands

The root `Makefile` separates local development from production deployment.
Local targets use `docker-compose.yml` plus the Vite dev server. Production
targets delegate to the existing `docker-compose.prod.yml` flow.

## Local Development

Install frontend dependencies once:

```sh
make fe-install
```

Start the local backend/dependency stack and the frontend dev server:

```sh
make local
```

`make dev` is the same as `make local`.

The frontend in this flow is Vite dev mode with hot reload. It is not a
production frontend build and it does not upload assets to S3/CDN.

Local URLs:

```text
Frontend: http://localhost:3000
Gateway:  http://localhost:8000
LiveKit:  ws://localhost:7880
MongoDB:  localhost:27017
```

The local Docker stack uses `.env.local` when present. If `.env.local` does not
exist, Make falls back to `.env.local.example`. Copy it when you need real local
values:

```sh
cp .env.local.example .env.local
```

Set a real `OPENAI_API_KEY` in `.env.local` for live AI translation. Do not
commit `.env.local`.

Frontend Vite env defaults are in `FE/.env.development` and `FE/.env.example`:

```text
VITE_APP_ORIGIN=http://localhost:3000
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
VITE_LIVEKIT_WS_URL=ws://localhost:7880
```

Common local commands:

```sh
make local-services
make logs
make ps
make down
make clean
```

`make clean` removes local containers/orphans only. It does not delete Docker
volumes or Mongo data.

## Production

Production continues to use the existing compose deploy file:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

The Makefile aliases are:

```sh
make prod
make ps-prod
make logs-prod
make down-prod
```

Before production deploy, create and edit the production env file:

```sh
cp .env.example .env.production
```

Replace all placeholder secrets before running `make prod`. The Makefile refuses
to start production when uncommented env values still contain placeholder text.

## Validation

These checks do not start services:

```sh
make config
make config-prod
```

Use `make config-prod PROD_ENV_FILE=.env.example` only for syntax validation
against the template; production deploy should use a real `.env.production`.
