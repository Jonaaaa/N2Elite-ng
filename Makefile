# N2Elite-ng — build system (Linux + Windows), Python base + Tkinter GUI.
#
#   make install       install app + deps into ./.venv (editable)
#   make gui           launch the GUI
#   make run ARGS=...  run the CLI (e.g. make run ARGS="read -o tag.bin")
#   make test          run the offline test suite
#   make build-linux   standalone Linux binary  -> dist/n2elite-ng
#   make build-windows standalone Windows .exe   -> dist/windows/n2elite-ng.exe (needs Wine)
#   make dist          build for the current OS
#   make clean         remove build artifacts

PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin
PYBIN   := $(BIN)/python
PIP     := $(BIN)/pip

.DEFAULT_GOAL := help
.PHONY: help venv install gui run test build-linux build-windows dist clean distclean

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

venv:  ## create the virtualenv
	$(PY) -m venv $(VENV)
	$(PIP) install -q -U pip

install: venv  ## install the app and its dependencies (editable)
	$(PIP) install -q -e .
	@echo "Installed. Run 'make gui' or '$(BIN)/n2elite-ng --help'."

gui: install  ## launch the graphical interface
	$(PYBIN) -m n2elite gui

run: install  ## run the CLI: make run ARGS="read -o tag.bin"
	$(PYBIN) -m n2elite $(ARGS)

test: install  ## run the offline test suite
	@for t in tests/test_*.py; do echo "== $$t"; $(PYBIN) $$t || exit 1; done

build-linux: install  ## build a standalone Linux binary -> dist/n2elite-ng
	$(PIP) install -q -U pyinstaller
	$(BIN)/pyinstaller --noconfirm --clean n2elite.spec
	@echo "Built: dist/n2elite-ng"

build-windows:  ## build a standalone Windows .exe via Wine -> dist/windows/
	./tools/build_windows.sh

dist:  ## build for the current OS
ifeq ($(OS),Windows_NT)
	@$(MAKE) build-windows
else
	@$(MAKE) build-linux
endif

clean:  ## remove build artifacts
	rm -rf build dist __pycache__ */__pycache__ */*/__pycache__ *.egg-info .pytest_cache
	find . -name '*.pyc' -delete

distclean: clean  ## also remove the virtualenv
	rm -rf $(VENV)
