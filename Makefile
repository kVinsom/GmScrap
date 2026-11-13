.DEFAULT_GOAL := help

DOCKER ?= docker
COMPOSE = $(DOCKER) compose
ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python.exe
else
PYTHON ?= .venv/bin/python
endif

export SEARCH_CENTER ?= 49.8415, 24.0315
export SEARCH_CATEGORY ?= cafe
export SEARCH_RADIUS ?= 5000
export SEARCH_NAME ?=

.PHONY: help all config build build-test run check test lint format-check \
        install check-local format down release

help:
	@echo "make all          Build production image and run all container checks"
	@echo "make build        Build production image"
	@echo "make run          Run a search using SEARCH_CENTER/CATEGORY/RADIUS/NAME"
	@echo "make check        Build test image; run tests, lint and format checks"
	@echo "make test         Build test image; run tests only"
	@echo "make lint         Build test image; run Ruff lint"
	@echo "make format-check Build test image; check formatting"
	@echo "make config       Validate Compose configuration"
	@echo "make install      Install pinned development dependencies in local venv"
	@echo "make check-local  Run all checks with local Python"
	@echo "make format       Fix imports and format local source and tests"
	@echo "make down         Remove project containers and networks"
	@echo "make release      Test, build and validate local release artifacts in dist/"

all: build check

config:
	$(COMPOSE) --profile tools config --quiet

build: config
	$(COMPOSE) build gmscrap

build-test: config
	$(COMPOSE) --profile tools build tests

# Build first with `make build`; keep search stdout usable as JSON.
run:
	@$(COMPOSE) run --rm --no-deps -T gmscrap

check: build-test
	$(COMPOSE) --profile tools run --rm --no-deps -T tests

test: build-test
	$(COMPOSE) --profile tools run --rm --no-deps -T tests -m unittest discover -s tests -v

lint: build-test
	$(COMPOSE) --profile tools run --rm --no-deps -T tests -m ruff check .

format-check: build-test
	$(COMPOSE) --profile tools run --rm --no-deps -T tests -m ruff format --check .

install:
	"$(PYTHON)" -m pip install -r requirements-dev.txt
	"$(PYTHON)" -m pip install --no-build-isolation --no-deps -e .
	"$(PYTHON)" -m pip check

check-local:
	"$(PYTHON)" run_tests.py

format:
	"$(PYTHON)" -m ruff check --fix .
	"$(PYTHON)" -m ruff format .

down:
	$(COMPOSE) --profile tools down --remove-orphans

release:
	"$(PYTHON)" scripts/release.py
