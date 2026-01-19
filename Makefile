.PHONY: help build up down logs shell clean test

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build the Docker image
	docker compose build

up: ## Start the services
	docker compose up -d
	@echo "Services started!"
	@echo "FastAPI: http://localhost:8000"
	@echo "Swagger Docs: http://localhost:8000/docs"
	@echo "noVNC Web: http://localhost:8080"
	@echo "VNC: localhost:5900 (password: teams123)"

down: ## Stop the services
	docker compose down

restart: down up ## Restart the services

logs: ## Show logs
	docker compose logs -f

logs-api: ## Show API logs only
	docker compose logs -f teams-recorder

status: ## Show service status
	docker compose ps

shell: ## Open a shell in the container
	docker compose exec teams-recorder bash

shell-root: ## Open a root shell in the container
	docker compose exec -u root teams-recorder bash

clean: ## Clean up containers, volumes, and recordings
	docker compose down -v
	rm -rf recordings/* logs/*

test-api: ## Test the API with a sample request
	@echo "Testing API health endpoint..."
	curl -s http://localhost:8000/ | python -m json.tool

test-devices: ## List audio devices in the container
	docker compose exec teams-recorder python -c "from app.recorder import list_audio_devices; list_audio_devices()"

healthcheck: ## Check service health
	@echo "Checking teams-recorder health..."
	@docker inspect --format "{{json .State.Health }}" teams-meeting-recorder | python -m json.tool

install-dev: ## Install development dependencies
	pip install -r requirements.txt

format: ## Format code with black
	black app/

lint: ## Lint code with flake8
	flake8 app/

dev: ## Run the API locally (for development)
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
