VENV := .venv
PY := $(VENV)/bin/python
ROOT := ../..

install:
	python3.13 -m venv $(VENV)
	$(VENV)/bin/pip install -e .

test:
	$(PY) -m unittest discover tests -v

# Три режими: negative/positive доводять межу на Bash, read_edit доводить
# ту саму межу на Read і Edit (обов'язок 2, спец, розділ 5.3, "Відома діра
# probe, яку продукт мусить закрити"). Усі три - `&&`, тому перший FAIL чи
# ненульовий exit зупиняє послідовність одразу, а не ховається за
# наступними викликами.
probe:
	$(PY) probe_sandbox.py negative && \
	$(PY) probe_sandbox.py positive && \
	$(PY) probe_sandbox.py read_edit

run:
	cd $(ROOT) && tools/sync_features/$(PY) tools/sync_features/sync_features.py

run-broken:
	cd $(ROOT) && SYNC_FEATURES_BROKEN_PROMPT=1 \
		tools/sync_features/$(PY) tools/sync_features/sync_features.py

# Навмисно НЕ чіпає Features_list.json - див. README.md, розділ "Чому
# clean не робить git restore".
clean:
	rm -rf sync-artifacts

.PHONY: install test probe run run-broken clean
