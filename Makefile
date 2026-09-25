SHELL := /bin/bash
PROJECT := asignacion-estudiantes-service
PKG := asignacion_estudiantes_service

.PHONY: install run-api run-worker format lint precommit docker-up docker-down docker-logs docker-build test

install:
	poetry install

run-api:
	PYTHONPATH=src poetry run python -m $(PKG).main_api

run-worker:
	PYTHONPATH=src poetry run python -m $(PKG).main_worker

test:
	PYTHONPATH=src poetry run pytest -q

format:
	PYTHONPATH=src poetry run ruff format .
	PYTHONPATH=src poetry run ruff check . --fix

lint:
	PYTHONPATH=src poetry run ruff check .

precommit:
	poetry run pre-commit install

docker-build:
	docker build -t $(PROJECT):latest .

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

docker-logs:
	docker compose logs -f
