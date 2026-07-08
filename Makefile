PYTHON ?= /opt/homebrew/opt/python@3.13/bin/python3.13

.PHONY: test test-all lint typecheck install cockpit

test:
	$(PYTHON) -m pytest tests/ --ignore=tests/reference -q

test-all:
	$(PYTHON) -m pytest tests/ -q

lint:
	$(PYTHON) -m ruff check eagleeye tests/

typecheck:
	$(PYTHON) -m mypy eagleeye/

install:
	$(PYTHON) -m pip install -e ".[dev]"

cockpit:
	eagleeye cockpit --open
