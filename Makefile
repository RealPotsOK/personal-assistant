.PHONY: build up down logs test lint status \
	controller-build controller-up controller-down controller-logs controller-test controller-lint \
	qwen-build qwen-up qwen-down qwen-logs qwen-test \
	whisper-build whisper-up whisper-down whisper-logs whisper-test \
	xtts-build xtts-up xtts-down xtts-logs xtts-test

build: controller-build

up: controller-up

down: controller-down

logs: controller-logs

test: controller-test qwen-test whisper-test xtts-test

lint: controller-lint

status:
	docker compose ps
	cd qwen3-8b-vl && docker compose ps
	cd whisper && docker compose ps
	cd xtts-voice && docker compose ps

controller-build:
	docker compose build

controller-up:
	docker compose up -d --build

controller-down:
	docker compose down

controller-logs:
	docker compose logs -f controller

controller-test:
	.venv/bin/python -m pytest -q

controller-lint:
	.venv/bin/ruff check app tests

qwen-build:
	cd qwen3-8b-vl && docker compose build

qwen-up:
	cd qwen3-8b-vl && docker compose up -d --build

qwen-down:
	cd qwen3-8b-vl && docker compose down

qwen-logs:
	cd qwen3-8b-vl && docker compose logs -f qwen-api

qwen-test:
	cd qwen3-8b-vl && if [ -x .venv/bin/python ]; then .venv/bin/python -m pytest -q; else python3 -m pytest -q; fi

whisper-build:
	cd whisper && docker compose build

whisper-up:
	cd whisper && docker compose up -d --build

whisper-down:
	cd whisper && docker compose down

whisper-logs:
	cd whisper && docker compose logs -f whisper-api

whisper-test:
	cd whisper && if [ -x .venv/bin/python ]; then .venv/bin/python -m pytest -q; else python3 -m pytest -q; fi

xtts-build:
	cd xtts-voice && docker compose build

xtts-up:
	cd xtts-voice && docker compose up -d --build

xtts-down:
	cd xtts-voice && docker compose down

xtts-logs:
	cd xtts-voice && docker compose logs -f xtts-api

xtts-test:
	cd xtts-voice && if [ -x .venv/bin/python ]; then .venv/bin/python -m pytest -q; else python3 -m pytest -q; fi
