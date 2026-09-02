# Reproduction entry points. See README.md for what each target produces.
PY := .venv/bin/python

.PHONY: help venv data test validate examples experiments smoke-test clean

help:
	@echo "make venv        create the pinned virtual environment"
	@echo "make data        fetch and SHA-verify the Titan GPU lifetime dataset"
	@echo "make test        the test suite, including the mutation tests (~4 min)"
	@echo "make validate    the validation registry and the list of what it declines"
	@echo "make examples    run every example input through the CLI"
	@echo "make experiments the three figures the README quotes"
	@echo "make smoke-test  tests, registry and examples (~5 min)"
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

examples:
	$(PY) examples/run_examples.py

experiments:
	PYTHONPATH=src $(PY) experiments/failure_exposure.py
	PYTHONPATH=src $(PY) experiments/fragmentation_curve.py
	PYTHONPATH=src $(PY) experiments/isolation_cost.py

smoke-test: test validate examples

clean:
	rm -rf build dist src/*.egg-info .pytest_cache
