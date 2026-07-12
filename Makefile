.DEFAULT_GOAL := help
COMPOSE := docker compose -f infra/compose/docker-compose.yml

.PHONY: help install demo synth test lint type up down seed logs clean openapi openapi-check build-images

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS=":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

install: ## Install the whole workspace (editable)
	pip install -e ".[dev,api]"

demo: ## Run the deploy-will-fail scenario end to end (in-memory)
	cortex-demo

synth: ## Print the synthetic source events as JSON
	cortex-synth

test: ## Run unit + integration + e2e tests
	pytest

lint: ## Lint with ruff
	ruff check .

type: ## Type-check with mypy (strict)
	mypy

up: ## Start the full stack (Kafka/Neo4j/Qdrant/Redis/Postgres + services + dashboard)
	$(COMPOSE) up -d

down: ## Tear down the stack
	$(COMPOSE) down -v

seed: ## Push the synthetic scenario through the running stack
	$(COMPOSE) exec api-service python -m cortex.tools.demo

logs: ## Tail all service logs
	$(COMPOSE) logs -f

openapi: ## Regenerate committed OpenAPI specs (docs/api/openapi/*.json)
	python tools/scripts/dump_openapi.py

openapi-check: ## Fail if committed OpenAPI specs are stale
	python tools/scripts/dump_openapi.py --check

build-images: ## Build every service image from its own Dockerfile
	@for s in ingestion entity graph retrieval ranking llm notification api; do \
		echo "building cortex/$$s-service"; \
		docker build -f services/$$s-service/Dockerfile -t cortex/$$s-service . || exit 1; \
	done

clean: ## Remove caches and build artifacts
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
