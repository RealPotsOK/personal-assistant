.PHONY: download-model build up down logs test lint

MODEL_VARIANT ?= small.en
MODEL_PATH_HOST ?= /home/kevin/models/whisper/$(MODEL_VARIANT)

download-model:
	python3 scripts/download_model.py "$(MODEL_VARIANT)" "$(MODEL_PATH_HOST)"

build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f whisper-api

test:
	pytest -q

lint:
	ruff check app tests scripts
