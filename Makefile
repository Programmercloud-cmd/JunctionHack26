.PHONY: setup dev test
setup:
	bash scripts/bootstrap.sh
dev:
	.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
test:
	.venv/bin/python -m pytest -q
