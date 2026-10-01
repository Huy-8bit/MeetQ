COMPOSE := docker compose
COMPOSE_PROD_FILE := docker-compose.prod.yml
COMPOSE_LOCAL_FILE := docker-compose.yml
FE_DIR := FE
BE_DIR := BE

NPM := npm
FE_PORT ?= 3000
FE_PREVIEW_PORT ?= 4173

PROD_ENV_FILE ?= .env.production
LOCAL_ENV_FILE ?= .env.local
LOCAL_ENV_EXAMPLE_FILE := .env.local.example
LOCAL_ENV := $(if $(wildcard $(LOCAL_ENV_FILE)),$(LOCAL_ENV_FILE),$(LOCAL_ENV_EXAMPLE_FILE))

PROD_COMPOSE := $(COMPOSE) --env-file $(PROD_ENV_FILE) -f $(COMPOSE_PROD_FILE)
LOCAL_COMPOSE := $(COMPOSE) --env-file $(LOCAL_ENV) -f $(COMPOSE_LOCAL_FILE)

.DEFAULT_GOAL := help

.PHONY: help check-docker check-prod-env-file check-prod-env prod up-prod dev local local-services \
	down down-prod logs logs-prod ps ps-prod clean config config-prod \
	fe-install fe-dev fe-lint fe-build fe-preview

help:
	@printf "%s\n" "brseAI Make targets:"
	@printf "\n%s\n" "Local development:"
	@printf "  %-20s %s\n" "make local" "Start local Docker services, then run FE Vite dev server."
	@printf "  %-20s %s\n" "make dev" "Alias for make local."
	@printf "  %-20s %s\n" "make local-services" "Start local backend/dependency services in Docker."
	@printf "  %-20s %s\n" "make down" "Stop local Docker services without deleting volumes."
	@printf "  %-20s %s\n" "make logs" "Tail local Docker service logs."
	@printf "  %-20s %s\n" "make ps" "List local Docker services."
	@printf "  %-20s %s\n" "make clean" "Remove local containers/orphans; preserve volumes and data."
	@printf "\n%s\n" "Frontend local helpers:"
	@printf "  %-20s %s\n" "make fe-install" "Install frontend dependencies with npm ci."
	@printf "  %-20s %s\n" "make fe-dev" "Run the FE dev server at http://localhost:$(FE_PORT)."
	@printf "  %-20s %s\n" "make fe-lint" "Run FE lint if package.json defines a lint script."
	@printf "  %-20s %s\n" "make fe-build" "Run local FE build check; does not deploy."
	@printf "  %-20s %s\n" "make fe-preview" "Preview built FE locally at http://localhost:$(FE_PREVIEW_PORT)."
	@printf "\n%s\n" "Production:"
	@printf "  %-20s %s\n" "make prod" "Build and start the existing production compose stack."
	@printf "  %-20s %s\n" "make up-prod" "Alias for make prod."
	@printf "  %-20s %s\n" "make down-prod" "Stop production compose services without deleting volumes."
	@printf "  %-20s %s\n" "make logs-prod" "Tail production compose logs."
	@printf "  %-20s %s\n" "make ps-prod" "List production compose services."
	@printf "\n%s\n" "Validation:"
	@printf "  %-20s %s\n" "make config" "Validate local compose config."
	@printf "  %-20s %s\n" "make config-prod" "Validate production compose config."

check-docker:
	@$(COMPOSE) version >/dev/null

check-prod-env-file:
	@test -f $(PROD_ENV_FILE) || { \
		printf "%s\n" "Missing $(PROD_ENV_FILE). Create it with: cp .env.example $(PROD_ENV_FILE)"; \
		exit 1; \
	}

check-prod-env: check-prod-env-file
	@if grep -E '^[A-Z0-9_]+=.*(replace-with|your_.*_here)' $(PROD_ENV_FILE) >/dev/null; then \
		printf "%s\n" "Refusing production start: replace placeholder values in $(PROD_ENV_FILE)."; \
		exit 1; \
	fi

prod up-prod: check-docker check-prod-env
	@$(PROD_COMPOSE) build
	@$(PROD_COMPOSE) up -d

dev local: check-docker
	@test -d $(FE_DIR)/node_modules || { \
		printf "%s\n" "Missing $(FE_DIR)/node_modules. Run: make fe-install"; \
		exit 1; \
	}
	@$(LOCAL_COMPOSE) up -d --build redis mongo livekit gateway interpreter
	@printf "%s\n" "Local backend is on http://localhost:8000; LiveKit is on ws://localhost:7880"
	@printf "%s\n" "Starting frontend dev server at http://localhost:$(FE_PORT)"
	@cd $(FE_DIR) && $(NPM) run dev -- --host 0.0.0.0 --port $(FE_PORT)

local-services: check-docker
	@$(LOCAL_COMPOSE) up -d --build redis mongo livekit gateway interpreter

down: check-docker
	@$(LOCAL_COMPOSE) down

down-prod: check-docker check-prod-env-file
	@$(PROD_COMPOSE) down

logs: check-docker
	@$(LOCAL_COMPOSE) logs -f

logs-prod: check-docker check-prod-env-file
	@$(PROD_COMPOSE) logs -f

ps: check-docker
	@$(LOCAL_COMPOSE) ps

ps-prod: check-docker check-prod-env-file
	@$(PROD_COMPOSE) ps

clean: check-docker
	@$(LOCAL_COMPOSE) down --remove-orphans
	@printf "%s\n" "Local containers/orphans removed. Docker volumes and Mongo data are preserved."

config: check-docker
	@$(LOCAL_COMPOSE) config -q

config-prod: check-docker check-prod-env-file
	@$(PROD_COMPOSE) config -q

fe-install:
	@cd $(FE_DIR) && $(NPM) ci

fe-dev:
	@printf "%s\n" "Starting frontend dev server at http://localhost:$(FE_PORT)"
	@cd $(FE_DIR) && $(NPM) run dev -- --host 0.0.0.0 --port $(FE_PORT)

fe-lint:
	@if node -e "const s = require('./$(FE_DIR)/package.json').scripts || {}; process.exit(s.lint ? 0 : 1)"; then \
		cd $(FE_DIR) && $(NPM) run lint; \
	else \
		printf "%s\n" "No frontend lint script found in $(FE_DIR)/package.json; skipping."; \
	fi

fe-build:
	@cd $(FE_DIR) && $(NPM) run build

fe-preview:
	@printf "%s\n" "Starting frontend preview at http://localhost:$(FE_PREVIEW_PORT)"
	@cd $(FE_DIR) && $(NPM) run preview -- --host 0.0.0.0 --port $(FE_PREVIEW_PORT)
