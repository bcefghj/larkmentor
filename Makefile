.PHONY: help install dev test lint format docker-build docker-up docker-down docker-logs health clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	pip install -r requirements.txt

dev: ## Run in development mode
	python main.py

test: ## Run all tests
	python -m pytest tests/ -v --tb=short

lint: ## Run linters
	ruff check .
	mypy --ignore-missing-imports core/ agent/ llm/ bot/

format: ## Auto-format code
	ruff format .
	ruff check --fix .

docker-build: ## Build Docker image
	docker compose build

docker-up: ## Start with Docker Compose
	docker compose up -d

docker-down: ## Stop Docker Compose
	docker compose down

docker-logs: ## View Docker logs
	docker compose logs -f agent-pilot

health: ## Check service health
	curl -s http://localhost:8001/health | python -m json.tool

clean: ## Clean cache and temp files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
