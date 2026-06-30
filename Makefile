# RailOS-X — developer convenience targets.
# Run `make help` for the list.

PYTHON ?= python

.DEFAULT_GOAL := help
.PHONY: help install test test-one infra services stop dashboard dashboard-build

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dev dependencies
	$(PYTHON) -m pip install -r requirements-dev.txt

test: ## Run all Python test suites (isolated per service)
	PYTEST="$(PYTHON) -m pytest" ./scripts/run_tests.sh

test-one: ## Run a single suite, e.g. `make test-one SUITE=services/adapters/tests`
	PYTEST="$(PYTHON) -m pytest" ./scripts/run_tests.sh $(SUITE)

infra: ## Start local infrastructure (docker compose)
	docker compose up -d

services: ## Start Python services natively (assumes infra is up)
	./scripts/local-dev/run_local.sh services

dashboard: ## Run the Operations Dashboard (Next.js dev server, :3000)
	cd dashboard && npm install && npm run dev

dashboard-build: ## Production build of the dashboard
	cd dashboard && npm install && npm run build

stop: ## Stop the local stack (containers + background services)
	./scripts/local-dev/run_local.sh stop
