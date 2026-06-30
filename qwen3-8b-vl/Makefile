.PHONY: build up down restart logs test shell config

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart: down build up

logs:
	docker compose logs -f qwen-api

test:
	pytest -q

shell:
	docker compose exec qwen-api /bin/bash

config:
	docker compose config
