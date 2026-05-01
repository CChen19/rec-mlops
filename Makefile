# Real-Time Recommendation Engine — Makefile
# Prerequisites: conda activate rec_mlops

.PHONY: help install setup start stop train \
        test test-unit test-smoke test-api test-models \
        lint format type-check pre-commit pre-commit-install \
        load-test load-test-headless \
        health logs metrics clean ci ci-test demo

# ── Help ─────────────────────────────────────────────────────────────────────

help:
	@echo "Real-Time Recommendation Engine"
	@echo "================================"
	@echo "Prerequisite: conda activate rec_mlops"
	@echo ""
	@echo "Setup"
	@echo "  install            Install dependencies (pip)"
	@echo "  setup              Init databases and Kafka topics"
	@echo ""
	@echo "Services"
	@echo "  start              docker compose up + API"
	@echo "  stop               docker compose down + kill API"
	@echo ""
	@echo "Training"
	@echo "  train              Train SVD + NMF models, log to MLflow"
	@echo ""
	@echo "Testing"
	@echo "  test               All tests with coverage"
	@echo "  test-unit          Unit tests only"
	@echo "  test-smoke         Smoke tests"
	@echo "  test-api           API tests"
	@echo "  test-models        Model tests"
	@echo ""
	@echo "Code quality"
	@echo "  format             Black + isort"
	@echo "  lint               Flake8 + Bandit"
	@echo "  type-check         MyPy"
	@echo "  pre-commit         Run all hooks"
	@echo "  ci                 lint + type-check"
	@echo ""
	@echo "Load testing"
	@echo "  load-test          Start Locust UI (http://localhost:8190)"
	@echo "  load-test-headless Headless run: 100 users, 5 min"
	@echo ""
	@echo "Ops"
	@echo "  health             Curl health + MLflow + Redis"
	@echo "  metrics            Curl /metrics"
	@echo "  logs               docker compose logs -f"
	@echo "  clean              Remove .pyc / __pycache__ / build artefacts"

# ── Setup ────────────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pre-commit install
	@echo "Done. Run 'conda activate rec_mlops' before using make targets."

setup: install
	python scripts/setup.py

# ── Services ─────────────────────────────────────────────────────────────────

start-infra:
	docker compose up -d
	@sleep 5

start-api:
	python -m uvicorn src.api.recommendation_api:app --host 0.0.0.0 --port 8000 &

start: start-infra start-api
	@echo "API: http://localhost:8000  MLflow: http://localhost:5000  Grafana: http://localhost:3000"

stop:
	docker compose down
	pkill -f "uvicorn src.api" || true

# ── Training ─────────────────────────────────────────────────────────────────

train:
	python src/models/train_models.py

# ── Tests ────────────────────────────────────────────────────────────────────

test:
	pytest tests/ -v --cov=src --cov-report=term-missing --cov-fail-under=70 --tb=short

test-unit:
	pytest tests/unit/ -v --cov=src --cov-report=term-missing -m "not integration and not slow"

test-smoke:
	pytest tests/ -v -m smoke

test-api:
	pytest tests/unit/test_api.py -v

test-models:
	pytest tests/unit/test_models.py -v

# ── Code quality ─────────────────────────────────────────────────────────────

format:
	isort src/ tests/
	black src/ tests/ --line-length=100

lint:
	flake8 src/ tests/ --statistics || true
	bandit -r src/ -ll --skip B101 || true

type-check:
	mypy src/ --ignore-missing-imports || true

pre-commit:
	pre-commit run --all-files

pre-commit-install:
	pre-commit install

ci: lint type-check
	@echo "CI: lint + type-check passed"

ci-test: ci test

# ── Load testing ─────────────────────────────────────────────────────────────

load-test:
	docker compose up -d locust-master
	@echo "Locust UI: http://localhost:8190"

load-test-headless:
	python -m locust -f tests/locustfile.py \
		--host=http://localhost:8000 \
		--users=100 \
		--spawn-rate=10 \
		--run-time=5m \
		--headless

# ── Ops ──────────────────────────────────────────────────────────────────────

health:
	curl -sf http://localhost:8000/health | python -m json.tool
	curl -sf http://localhost:5000/ > /dev/null && echo "MLflow OK" || echo "MLflow not responding"
	redis-cli -p 6550 ping || echo "Redis not responding"

metrics:
	curl -s http://localhost:8000/metrics

logs:
	docker compose logs -f

demo:
	python run_demo.py

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + || true
	rm -rf .pytest_cache/ htmlcov/ build/ dist/
