SHELL := /bin/bash

COMPOSE = docker compose $(if $(wildcard .env),--env-file .env)
UV = uv run

.PHONY: help setup up down logs health migrate format check test frontend-check test-frontend live-test \
	api worker frontend \
	start stop restart app-start app-stop app-restart start-backend stop-backend start-worker stop-worker start-frontend stop-frontend \
	status logs-backend logs-worker logs-frontend clean-logs

help:
	@echo "Search Anything - Available Commands"
	@echo "====================================="
	@echo ""
	@echo "Full Stack:"
	@echo "  make start          - Start infrastructure, migrate, and start all apps in background"
	@echo "  make stop           - Stop all background apps and infrastructure"
	@echo "  make restart        - Restart all background apps and infrastructure"
	@echo ""
	@echo "Infrastructure (Docker):"
	@echo "  make up             - Start infrastructure (PostgreSQL + RustFS)"
	@echo "  make down           - Stop infrastructure"
	@echo "  make migrate        - Run database migrations"
	@echo ""
	@echo "Application (Background with Logs):"
	@echo "  make app-start      - Start backend, worker, and frontend in background"
	@echo "  make app-stop       - Stop backend, worker, and frontend"
	@echo "  make app-restart    - Restart backend, worker, and frontend"
	@echo "  make start-backend  - Start backend API in background"
	@echo "  make stop-backend   - Stop backend API"
	@echo "  make start-worker   - Start background worker in background"
	@echo "  make stop-worker    - Stop background worker"
	@echo "  make start-frontend - Start Vite frontend in background"
	@echo "  make stop-frontend  - Stop Vite frontend"
	@echo ""
	@echo "Interactive Development (Foreground):"
	@echo "  make api            - Run API in foreground"
	@echo "  make worker         - Run worker in foreground"
	@echo "  make frontend       - Run frontend in foreground"
	@echo ""
	@echo "Logs & Status:"
	@echo "  make status         - Show infrastructure and local process status"
	@echo "  make health         - Health check for infrastructure and API"
	@echo "  make logs           - View Docker infrastructure logs (follow)"
	@echo "  make logs-backend   - View local backend logs (follow)"
	@echo "  make logs-worker    - View local worker logs (follow)"
	@echo "  make logs-frontend  - View local frontend logs (follow)"
	@echo "  make clean-logs     - Remove local log files"
	@echo ""
	@echo "Quality & Testing:"
	@echo "  make check          - Run backend lint/tests and frontend check/build"
	@echo "  make test           - Run backend unit tests"
	@echo "  make test-frontend  - Run frontend unit tests"
	@echo "  make format         - Format backend (Black) and frontend (Prettier)"
	@echo "  make live-test      - Run live infrastructure & model acceptance test"

setup:
	@test -f .env || cp .env.example .env
	uv sync
	cd frontend && pnpm install

up:
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	$(UV) search-anything migrate

api:
	@set -a; [ -f ./.env ] && . ./.env; set +a; \
	PORT=$${API_PORT:-8000}; \
	$(UV) uvicorn search_anything.api:app --host 127.0.0.1 --port $$PORT --reload

worker:
	$(UV) search-anything worker

frontend:
	@set -a; [ -f ./.env ] && . ./.env; set +a; \
	PORT=$${FRONTEND_PORT:-5173}; \
	cd frontend && pnpm dev --host 127.0.0.1 --port $$PORT

start-backend:
	@mkdir -p logs
	@set -a; [ -f ./.env ] && . ./.env; set +a; \
	PORT=$${API_PORT:-8000}; \
	if lsof -ti:$$PORT >/dev/null 2>&1; then \
		echo "Backend already running on port $$PORT"; \
	else \
		echo "Starting backend locally..."; \
		(PYTHONUNBUFFERED=1 $(UV) uvicorn search_anything.api:app --host 127.0.0.1 --port $$PORT --reload > logs/backend.log 2>&1 &); \
		echo "Backend started on port $$PORT"; \
		echo "Backend logs: logs/backend.log"; \
	fi

stop-backend:
	@echo "Stopping backend..."
	@set -a; [ -f ./.env ] && . ./.env; set +a; \
	PORT=$${API_PORT:-8000}; \
	lsof -ti:$$PORT | xargs kill -9 2>/dev/null || true; \
	pkill -f 'uvicorn search_anything.api:app' 2>/dev/null || true; \
	echo "Backend stopped"

start-worker:
	@mkdir -p logs
	@if pgrep -f 'search-anything worker' >/dev/null 2>&1; then \
		echo "Worker already running"; \
	else \
		echo "Starting worker..."; \
		(PYTHONUNBUFFERED=1 $(UV) search-anything worker > logs/worker.log 2>&1 &); \
		echo "Worker started"; \
		echo "Worker logs: logs/worker.log"; \
	fi

stop-worker:
	@echo "Stopping worker..."
	@pkill -f 'search-anything worker' 2>/dev/null || true; \
	echo "Worker stopped"

start-frontend:
	@mkdir -p logs
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "Frontend dependencies not found. Installing..."; \
		cd frontend && pnpm install; \
	fi
	@set -a; [ -f ./.env ] && . ./.env; set +a; \
	PORT=$${FRONTEND_PORT:-5173}; \
	if lsof -ti:$$PORT >/dev/null 2>&1; then \
		echo "Frontend already running on port $$PORT"; \
	else \
		echo "Starting frontend locally..."; \
		(cd frontend && pnpm exec vite --host 0.0.0.0 --port $$PORT > ../logs/frontend.log 2>&1 &); \
		echo "Frontend started on port $$PORT"; \
		echo "Frontend logs: logs/frontend.log"; \
	fi

stop-frontend:
	@echo "Stopping frontend..."
	@set -a; [ -f ./.env ] && . ./.env; set +a; \
	PORT=$${FRONTEND_PORT:-5173}; \
	lsof -ti:$$PORT | xargs kill -9 2>/dev/null || true; \
	pkill -f 'vite' 2>/dev/null || true; \
	echo "Frontend stopped"

app-start:
	@echo "Starting application services..."
	@$(MAKE) start-backend
	@$(MAKE) start-worker
	@$(MAKE) start-frontend
	@echo "Application services started"

app-stop:
	@echo "Stopping application services..."
	@$(MAKE) stop-backend
	@$(MAKE) stop-worker
	@$(MAKE) stop-frontend
	@echo "Application services stopped"

app-restart:
	@$(MAKE) app-stop
	@sleep 1
	@$(MAKE) app-start

start:
	@echo "Starting full stack..."
	@$(MAKE) up
	@$(MAKE) migrate
	@$(MAKE) app-start
	@echo ""
	@echo "All services started."
	@set -a; [ -f ./.env ] && . ./.env; set +a; \
	echo "  Frontend:    http://127.0.0.1:$${FRONTEND_PORT:-5173}"; \
	echo "  Backend API: http://127.0.0.1:$${API_PORT:-8000}"; \
	echo "  RustFS S3:   http://127.0.0.1:9000"; \
	echo "  RustFS Web:  http://127.0.0.1:9001"

stop:
	@echo "Stopping full stack..."
	@$(MAKE) app-stop
	@$(MAKE) down
	@echo "Full stack stopped"

restart:
	@$(MAKE) stop
	@sleep 1
	@$(MAKE) start

status:
	@echo "Infrastructure Services:"
	@$(COMPOSE) ps
	@echo ""
	@echo "Local Processes:"
	@pgrep -fl 'search-anything|vite' || echo "No local backend/worker/frontend processes running"
	@echo ""
	@echo "Health Checks:"
	@set -a; [ -f ./.env ] && . ./.env; set +a; \
	curl --fail --silent --show-error http://127.0.0.1:9000/health/ready >/dev/null 2>&1 && echo "  RustFS: healthy" || echo "  RustFS: unavailable"; \
	curl --fail --silent --show-error http://127.0.0.1:$${API_PORT:-8000}/health/ready >/dev/null 2>&1 && echo "  Backend API: ready" || echo "  Backend API: unavailable"

health:
	@$(COMPOSE) ps
	@set -a; [ -f ./.env ] && . ./.env; set +a; \
	curl --fail --silent --show-error http://127.0.0.1:9000/health/ready && echo "  RustFS healthy" || echo "  RustFS unavailable"; \
	curl --fail --silent --show-error http://127.0.0.1:$${API_PORT:-8000}/health/ready && echo "  Backend API ready" || echo "  Backend API unavailable"

logs-backend:
	@if [ -f logs/backend.log ]; then \
		echo "Viewing backend logs (Ctrl-C to exit)..."; \
		tail -f logs/backend.log; \
	else \
		echo "logs/backend.log not found"; \
	fi

logs-worker:
	@if [ -f logs/worker.log ]; then \
		echo "Viewing worker logs (Ctrl-C to exit)..."; \
		tail -f logs/worker.log; \
	else \
		echo "logs/worker.log not found"; \
	fi

logs-frontend:
	@if [ -f logs/frontend.log ]; then \
		echo "Viewing frontend logs (Ctrl-C to exit)..."; \
		tail -f logs/frontend.log; \
	else \
		echo "logs/frontend.log not found"; \
	fi

clean-logs:
	@rm -f logs/*.log
	@echo "Cleaned log files in logs/"

format:
	$(UV) black src tests
	cd frontend && pnpm format

check:
	$(UV) black --check src tests
	$(UV) ruff check src tests
	$(UV) pytest -q
	$(MAKE) frontend-check

test:
	$(UV) pytest -q

frontend-check:
	cd frontend && pnpm typecheck && pnpm lint && pnpm test && pnpm build

test-frontend:
	cd frontend && pnpm test

live-test:
	SEARCH_INTEGRATION_TESTS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
		$(UV) pytest -q tests/test_infrastructure_live.py -s
