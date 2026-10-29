# Repository Guidelines

## Project Structure & Module Organization

This is a Poetry-managed Python utility for local MQTT communication checks.
The CLI is interactive and validates an existing local stack; it does not
create profiles, devices, sensors, or controllers.

- `src/__main__.py` contains the CLI implementation: preflight checks, profile and feature selection, MQTT publishing, MongoDB/Redis verification, and controller command checks.
- `src/__init__.py` marks the package used by Poetry.
- `README.md` documents runtime services and environment variables.
- `Makefile` provides dependency installation, type checking, dependency auditing, packaging, and CLI commands through Poetry.
- `.github/workflows/build.yml` uses the Makefile commands in CI.

Do not add automated tests or a `tests/` directory to this project.

## Build, Test, and Development Commands

- `make deps` installs dependencies from `pyproject.toml` and `poetry.lock` (requires Poetry and Make).
- `make lint` runs Pyrefly static type checks.
- `make check` audits dependencies with pip-audit.
- `make run` runs the installed console script; use `make run ARGS="--all"` for non-interactive checks.
- `make build` creates distributable package artifacts and is the default target for `make`.

The checker expects Mosquitto, MongoDB, RabbitMQ, Redis, `producer`, `consumer`, and optionally `alarm-receiver`. It also requires `API_TOKEN_ENCRYPTION_KEY` from the API server environment. Use environment overrides from `README.md`, for example:

```bash
API_TOKEN_ENCRYPTION_KEY='<FROM_API_SERVER_ENV_VAR>' MQTT_HOST=localhost MONGO_URI=mongodb://localhost:27017 make run
```

## Coding Style & Naming Conventions

Use Python 3.12-compatible code. Follow PEP 8 with 4-space indentation, `snake_case` functions and variables, and uppercase constants such as `POLL_SECONDS`. Keep helpers small and explicit; prefer the standard library plus existing dependencies over new packages. Existing dependencies include `paho-mqtt`, `pymongo`, `redis`, `cryptography`, `pydantic`, and `questionary`.

Pyrefly is configured in `pyproject.toml` and runs through `make lint` locally and in CI. No formatter is configured. If adding one, wire it into Poetry and CI in the same change.

## Verification Guidelines

Do not add automated tests or configure a test framework. For code changes, run:

```bash
make lint
```

For end-to-end manual verification, run the CLI against the local stack and confirm it exits nonzero on failed preflight or verification checks.

## Commit & Pull Request Guidelines

Git history currently contains only `first commit`, so there is no established detailed convention. Use short, imperative commit subjects such as `add controller command checks` or `document redis preflight`.

Pull requests should include a summary, local commands run, affected environment variables or services, and relevant MQTT/MongoDB/Redis logs. Link related issues when available.

## Security & Configuration Tips

Do not commit real MQTT passwords, API tokens, MongoDB credentials, or Redis URLs. Keep secrets in environment variables. Defaults in the README are for local development only.

## Feature contract

The checker supports PM readings and gas indexes as floats, including registered `vocIndex`/`noxIndex` mapped to MQTT `voc-index`/`nox-index`. It supports `temperatureStatus` codes 0–5 via `temperature-status`, with separate nonzero alarms, plus motion, water-level, and thermostat mode-error alarms. Keep fallback ranges and spec-driven generation aligned with firmware and backend definitions. The ten networked device firmwares target ESP32-S3 only; the MCP9600 simulator does not register and is not a checker target.
