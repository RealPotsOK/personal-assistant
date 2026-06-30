.PHONY: download-model build up down logs test lint

download-model:
	@test "$(COQUI_TOS_AGREED)" = "1" || (echo "Read the CPML license, then run with COQUI_TOS_AGREED=1"; exit 1)
	COQUI_TOS_AGREED=1 python3 scripts/download_model.py "$${MODEL_PATH_HOST:-/home/kevin/models/xtts-v2}"

build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f xtts-api

test:
	pytest -q

lint:
	ruff check app tests scripts
