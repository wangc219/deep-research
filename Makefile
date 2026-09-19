.PHONY: check test architecture compile

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

architecture:
	PYTHONPATH=src $(PYTHON) -m equipment_deep_research.architecture

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

compile:
	PYTHONPATH=src $(PYTHON) -m compileall -q src

check: architecture compile
	PYTHONPATH=src $(PYTHON) -m pytest -q tests/equipment_deep_research/unit/test_architecture_boundaries.py tests/equipment_deep_research/unit/test_settings.py
