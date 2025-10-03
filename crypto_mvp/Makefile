.PHONY: all install fmt lint typecheck test run clean pre-commit pre-commit-install pre-commit-run pre-commit-update

all: install fmt lint typecheck test

install:
	pip install -r requirements.txt
	pip install pre-commit

fmt:
	black src tests
	isort src tests
	ruff check src tests --fix

lint:
	ruff check src tests
	bandit -r src/

typecheck:
	mypy src

test:
	pytest -q

test-cov:
	pytest --cov=src/crypto_mvp --cov-report=html --cov-report=term

run:
	python -m crypto_mvp

# Pre-commit hooks
pre-commit-install:
	pre-commit install

pre-commit-run:
	pre-commit run --all-files

pre-commit-update:
	pre-commit autoupdate

pre-commit: pre-commit-install pre-commit-run

# Docker commands
docker-build:
	docker build -t crypto-mvp .

docker-run:
	docker run --rm crypto-mvp --once

docker-dev:
	docker-compose up -d crypto-mvp-dev

docker-test:
	docker-compose exec crypto-mvp-dev pytest

# Development workflow
dev-setup: install pre-commit-install
	@echo "Development environment setup complete!"
	@echo "Run 'make pre-commit-run' to check code quality"

ci: fmt lint typecheck test
	@echo "CI checks passed!"

clean:
	find . -type f -name "*.pyc" | xargs rm -f
	find . -type d -name "__pycache__" | xargs rm -rf
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	rm -rf venv
	rm -rf htmlcov
	rm -f .coverage
	rm -f bandit-report.json
	rm -f safety-report.json
