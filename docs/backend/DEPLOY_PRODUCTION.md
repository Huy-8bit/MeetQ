# Production Deploy: meetqapp.com

Scope: one server, Docker Compose, Nginx reverse proxy.

## DNS

Create these records pointing to the same server public IP:

| Host | Type | Value |
| --- | --- | --- |
| `meetqapp.com` | `A` | server public IPv4 |
| `www.meetqapp.com` | `A` | server public IPv4 |
| `rtc.meetqapp.com` | `A` | server public IPv4 |

Cloudflare recommendation:

- `meetqapp.com`: proxied is acceptable for FE, REST, and Gateway WebSocket. DNS only is also fine.
- `rtc.meetqapp.com`: use DNS only. LiveKit signaling is proxied by Nginx, but WebRTC media UDP must reach the server directly.

## Public Routing

| Public URL | Nginx upstream |
| --- | --- |
| `https://meetqapp.com/` | `fe:80` |
| `https://meetqapp.com/api/...` | `gateway:8000` |
| `wss://meetqapp.com/ws/...` | `gateway:8000` |
| `wss://rtc.meetqapp.com` | `livekit:7880` |

Internal only:

- `gateway:8000`
- `fe:80`
- `interpreter`
- `redis:6379`
- `livekit:7880` signaling, except through Nginx

## Firewall Ports

Open:

| Port | Proto | Purpose |
| --- | --- | --- |
| `80` | TCP | HTTP redirect and ACME challenge |
| `443` | TCP | HTTPS, Gateway WS, LiveKit signaling |
| `7881` | TCP | LiveKit ICE TCP fallback |
| `50000-50100` | UDP | LiveKit WebRTC media |

Do not expose publicly:

- `8000/tcp` Gateway
- `3000/tcp` or FE internal port
- `6379/tcp` Redis
- `7880/tcp` LiveKit signaling

## Environment

Create a production env file:

```bash
cp .env.example .env.production
```

Edit secrets before deploy:

- `OPENAI_API_KEY`
- `ROOM_JWT_SECRET`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`

Production public URL values should stay:

```text
LIVEKIT_WS_URL_PUBLIC=wss://rtc.meetqapp.com
LIVEKIT_WS_URL_INTERNAL=ws://livekit:7880
PUBLIC_APP_URL=https://meetqapp.com
PUBLIC_GATEWAY_URL=https://meetqapp.com
PUBLIC_GATEWAY_WS_URL=wss://meetqapp.com
VITE_API_BASE_URL=
```

`VITE_API_BASE_URL=` intentionally leaves the frontend on same-origin production routing.

## SSL

This repo does not automate certificate issuance yet. The production Nginx config expects certificates at:

```text
/etc/letsencrypt/live/meetqapp.com/fullchain.pem
/etc/letsencrypt/live/meetqapp.com/privkey.pem
/etc/letsencrypt/live/rtc.meetqapp.com/fullchain.pem
/etc/letsencrypt/live/rtc.meetqapp.com/privkey.pem
```

One practical bootstrap path on a fresh server:

```bash
sudo certbot certonly --standalone -d meetqapp.com -d www.meetqapp.com
sudo certbot certonly --standalone -d rtc.meetqapp.com
```

Then deploy the stack. If using a different ACME client, set `SSL_CERTS_DIR` in `.env.production` so the compose mount provides `/etc/letsencrypt` inside the Nginx container.

## Start

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Equivalent Makefile aliases:

```bash
make prod
make ps-prod
make logs-prod
make down-prod
```

`make prod` uses the existing `docker-compose.prod.yml` flow and requires
`.env.production`. It does not delete Docker volumes or data.

## Smoke Checks

```bash
curl -I https://meetqapp.com/
curl -I https://meetqapp.com/api/health
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f nginx gateway livekit
```

Browser join responses should contain:

- Gateway WebSocket: `wss://meetqapp.com/ws/...`
- LiveKit URL: `wss://rtc.meetqapp.com`
- Share URL: `https://meetqapp.com/rooms/...`

Local development remains on `docker-compose.yml` and local FE dev server defaults.
