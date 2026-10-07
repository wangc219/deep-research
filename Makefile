.PHONY: check test architecture compile

UV ?= uv
PLATFORM_PYTHONPATH := backend:backend/package

architecture:
	PYTHONPATH=$(PLATFORM_PYTHONPATH) $(UV) run --project backend python -m equipment_deep_research.architecture

test:
	$(UV) run --project backend pytest -q backend/test/unit

compile:
	PYTHONPATH=$(PLATFORM_PYTHONPATH) $(UV) run --project backend python -m compileall -q \
		backend/package/platform_core backend/package/equipment_deep_research backend/server

check: architecture compile
	$(UV) run --project backend pytest -q \
		backend/test/unit/architecture/test_equipment_domain_boundaries.py \
		backend/test/equipment_deep_research/unit/test_architecture_boundaries.py \
		backend/test/equipment_deep_research/unit/test_settings.py
