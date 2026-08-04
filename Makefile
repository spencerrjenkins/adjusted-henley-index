# Reproduce the whole project. `make all` from a clean checkout is the contract.
PY := .venv/bin/python
export PYTHONPATH := src

.PHONY: all venv fetch run test verify site clean distclean

all: venv fetch run test          ## fetch data, run the pipeline, run the tests

venv:                             ## create the virtualenv and install pinned deps
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt

fetch:                            ## download every upstream source into data/raw/
	$(PY) -m ahi.ingest.fetch

refetch:                          ## force re-download, ignoring the cache
	$(PY) -m ahi.ingest.fetch --force

run:                              ## build tables, figures, results.json and docs/
	$(PY) -m ahi.pipeline

test:                             ## run the invariant tests
	$(PY) -m pytest

verify:                           ## assert the committed outputs match a clean rebuild (what CI runs)
	$(PY) -m ahi.regen_check

serve:                            ## preview the data story locally
	$(PY) -m http.server 8000 --directory docs

clean:                            ## remove generated outputs (keeps raw data)
	rm -rf output/tables output/figures output/results.json data/processed docs/figures docs/data docs/index.html

distclean: clean                  ## also remove downloaded data and the venv
	rm -rf data/raw .venv

help:                             ## list targets
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'
