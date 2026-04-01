PROJECT_NAME := interactive_annotation

.PHONY: up down logs build config release release-test

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

build:
	docker compose build

config:
	docker compose config

release:
	bash scripts/create_release_bundle.sh

release-test:
	bash scripts/release_test_bundle.sh
