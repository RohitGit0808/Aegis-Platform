# Aegis — developer task runner.
# Recipes use TABS (required by GNU Make). `make` with no target prints help.

.DEFAULT_GOAL := help

# Allow `make revision m="add foo"` to pass a message to alembic.
m ?= migration

COMPOSE := docker compose -f docker/docker-compose.yml

.PHONY: help install run worker seed test lint format typecheck \
        migrate revision compose-up compose-down docker-build

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install the package with dev extras (editable).
	pip install -e ".[dev]"

run: ## Run the API with autoreload.
	uvicorn aegis.main:app --reload

worker: ## Run the arq background worker.
	arq aegis.workers.arq_worker.WorkerSettings

seed: ## Seed an admin user and the demo suite.
	aegis seed

test: ## Run the test suite (sqlite + fakeredis, no services needed).
	pytest

lint: ## Lint with ruff.
	ruff check .

format: ## Auto-format with ruff.
	ruff format .

typecheck: ## Type-check the package with mypy.
	mypy src

migrate: ## Apply all pending Alembic migrations.
	alembic upgrade head

revision: ## Autogenerate a migration: make revision m="message".
	alembic revision --autogenerate -m "$(m)"

compose-up: ## Start the full stack via docker compose.
	$(COMPOSE) up -d --build

compose-down: ## Stop the stack and remove volumes.
	$(COMPOSE) down -v

docker-build: ## Build the application image.
	docker build -f docker/Dockerfile -t aegis-platform:local .
