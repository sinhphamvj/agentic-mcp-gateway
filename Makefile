.PHONY: install test lint format serve docker-up

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run mypy gateway

format:
	uv run ruff format .
	uv run ruff check --fix .

serve:
	uv run amcpg serve

docker-up:
	docker compose up --build
