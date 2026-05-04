.PHONY: install dev test lint format type docker-build docker-up docker-down

install:
	pip install -e ".[dev,fallback]"

dev:
	uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --reload

test:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check app tests

format:
	black app tests
	ruff check --fix app tests

type:
	mypy --strict app

docker-build:
	docker compose -f docker/docker-compose.yml build

docker-up:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down
