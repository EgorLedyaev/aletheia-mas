# Aletheia -- one-command setup and demo.
PY ?= python

.PHONY: setup demo demo-offline test tools scenarios registry eval ui clean

setup:
	$(PY) -m pip install -e .
	$(PY) scripts/fetch_vina.py
	$(PY) scripts/verify_registry.py
	@echo "setup complete -- run 'make demo'"

demo:
	$(PY) -m aletheia.cli scenarios --run

demo-offline:
	ALETHEIA_OFFLINE=1 $(PY) -m aletheia.cli scenarios --run

test:
	$(PY) -m pytest tests -q

tools:
	$(PY) -m aletheia.cli tools

scenarios:
	$(PY) -m aletheia.cli scenarios

registry:
	$(PY) scripts/verify_registry.py

eval:
	$(PY) -m eval.harness

ui:
	$(PY) -m uvicorn aletheia.web.app:app --host 127.0.0.1 --port 8000

clean:
	rm -rf runs/*.jsonl runs/*.answer.* __pycache__ .pytest_cache
