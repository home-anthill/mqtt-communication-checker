.DEFAULT_GOAL := build

lint:
	poetry run pyrefly check
.PHONY: lint

check:
	poetry run pip-audit --skip-editable
.PHONY: check

build:
	poetry build
.PHONY: build

run:
	poetry run mqtt-communication-checker $(ARGS)
.PHONY: run

deps:
	poetry install
.PHONY: deps
