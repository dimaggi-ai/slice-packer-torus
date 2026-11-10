# Reproduction entry points. See README.md for what each target produces.
PY := .venv/bin/python

.PHONY: help venv data test validate examples experiments experiments-ocs ocs-smoke smoke-test clean

help:
	@echo "make venv        create the pinned virtual environment"
	@echo "make data        fetch and SHA-verify the Titan GPU lifetime dataset"
	@echo "make test        the test suite, including the mutation tests (~4 min)"
	@echo "make validate    both validation registries (static and OCS) and what each declines"
	@echo "make examples    run every example input through the CLI"
	@echo "make experiments the three figures the README quotes"
	@echo "make experiments-ocs  the full OCS vs static comparison (~4 min)"
	@echo "make ocs-smoke   the OCS comparison with reduced trials (~45 s)"
	@echo "make smoke-test  tests, both registries, examples and the OCS smoke run (~6 min)"
	@echo "make clean       remove build artifacts"

venv:
	python3.12 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -e ".[dev]"

data:
	sh data/fetch_titan.sh

test: data
	PYTHONPATH=src:validation $(PY) -m pytest tests/ -q

validate: data
	$(PY) validation/validate_packing.py
	PYTHONPATH=src:validation $(PY) validation/validate_ocs.py

examples:
	$(PY) examples/run_examples.py

experiments:
	PYTHONPATH=src $(PY) experiments/failure_exposure.py
	PYTHONPATH=src $(PY) experiments/fragmentation_curve.py
	PYTHONPATH=src $(PY) experiments/isolation_cost.py

experiments-ocs:
	PYTHONPATH=src $(PY) experiments/ocs/compare.py

ocs-smoke:
	PYTHONPATH=src $(PY) experiments/ocs/compare.py --quick

smoke-test: test validate examples ocs-smoke

clean:
	rm -rf build dist src/*.egg-info .pytest_cache
