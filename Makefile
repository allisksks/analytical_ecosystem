.PHONY: help setup dev-db dev-api dev-web demo-data test lint fmt openapi up down

help:  ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup:  ## Install backend and frontend dependencies
	cd backend && uv sync
	cd frontend && npm ci

dev-db:  ## Start Postgres, Valkey and ClickHouse for local development
	docker compose -f deploy/docker-compose.dev.yml up -d

dev-api:  ## Run API with auto-reload
	cd backend && uv run alembic upgrade head && uv run uvicorn app.main:app --reload --port 8000

dev-web:  ## Run Vite dev server
	cd frontend && npm run dev

demo-data:  ## Generate demo game data into backend/demo-data
	cd backend && uv run python -m scripts.generate_demo_data --out ./demo-data

test:  ## Run all tests
	cd backend && uv run pytest --cov
	cd frontend && npm test

lint:  ## Lint and type-check everything
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
	cd frontend && npm run lint && npm run typecheck && npm run format:check

fmt:  ## Auto-format
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format

openapi:  ## Regenerate OpenAPI schema and the typed frontend client
	cd backend && uv run python -m scripts.export_openapi ../frontend/src/shared/api/openapi.json
	cd frontend && npm run gen:api && npx prettier --write src/shared/api/schema.d.ts

up:  ## Build and start the full stack with demo data
	docker compose --profile demo run --rm demo-data
	docker compose up -d --build

down:  ## Stop the stack
	docker compose down
