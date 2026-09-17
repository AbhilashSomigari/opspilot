.PHONY: up down test eval baseline logs

up:
	cp -n .env.example .env || true
	docker compose up --build -d

down:
	docker compose down

test:
	python -m pytest -q

baseline:
	python eval/baseline.py

eval:
	python eval/runner.py

logs:
	docker compose logs -f agent checkout payment catalog
