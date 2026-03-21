.PHONY: run worker dev test lint migrate migrate-create frontend

# ── Backend ──
run:
	uv run uvicorn backend.main:app --reload --port 8000

worker:
	uv run python worker.py

# ── Frontend ──
frontend:
	cd frontend-next && npm run dev

# ── Both (parallel) ──
dev:
	make run & make frontend & wait

# ── Testing ──
test:
	uv run pytest tests/ -v

lint:
	uv run ruff check backend/ tests/
	uv run ruff format --check backend/ tests/

fix:
	uv run ruff check --fix backend/ tests/
	uv run ruff format backend/ tests/

# ── Database Migrations ──
migrate:
	uv run alembic upgrade head

migrate-create:
	@read -p "Migration message: " msg && uv run alembic revision -m "$$msg"

migrate-down:
	uv run alembic downgrade -1

migrate-history:
	uv run alembic history

# ── Dependencies ──
install:
	uv sync
	cd frontend-next && npm install

install-dev:
	uv sync --all-extras
	cd frontend-next && npm install
