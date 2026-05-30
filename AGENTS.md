# Repository Guidelines

## Project Structure & Module Organization

This is a Poetry-managed Python utility for local MQTT communication checks.
The CLI is interactive and validates an existing local stack; it does not
create profiles, devices, sensors, or controllers.

- `src/__main__.py` contains the CLI implementation: preflight checks, profile and feature selection, MQTT publishing, MongoDB/Redis verification, and controller command checks.
- `src/__init__.py` marks the package used by Poetry.
- `check_mqtt_communication.py` is a thin compatibility runner that calls `src.__main__.main()`.
- `README.md` documents runtime services and environment variables.
- `.github/workflows/build.yml` installs the project with Poetry in CI.

Do not add automated tests or a `tests/` directory to this project.

## Build, Test, and Development Commands

- `poetry install` installs runtime dependencies from `pyproject.toml` and `poetry.lock`.
- `poetry run mqtt-communication-checker` runs the installed console script.
- `poetry run python check_mqtt_communication.py` runs the compatibility entry point.
- `poetry build` creates distributable package artifacts.

The checker expects Mosquitto, MongoDB, RabbitMQ, Redis, `producer`, `consumer`, and optionally `online-receiver`. It also requires `API_TOKEN_ENCRYPTION_KEY` from the API server environment. Use environment overrides from `README.md`, for example:

```bash
API_TOKEN_ENCRYPTION_KEY='<FROM_API_SERVER_ENV_VAR>' MQTT_HOST=localhost MONGO_URI=mongodb://localhost:27017 poetry run mqtt-communication-checker
```

## Coding Style & Naming Conventions

Use Python 3.12-compatible code. Follow PEP 8 with 4-space indentation, `snake_case` functions and variables, and uppercase constants such as `POLL_SECONDS`. Keep helpers small and explicit; prefer the standard library plus existing dependencies over new packages. Existing dependencies include `paho-mqtt`, `pymongo`, `redis`, `cryptography`, `pydantic`, and `questionary`.

No formatter or linter is configured. If adding one, wire it into Poetry and CI in the same change.

## Verification Guidelines

Do not add automated tests or configure a test framework. For code changes, use lightweight manual or syntax verification such as:

```bash
poetry run python -m compileall src
```

For end-to-end manual verification, run the CLI against the local stack and confirm it exits nonzero on failed preflight or verification checks.

## Commit & Pull Request Guidelines

Git history currently contains only `first commit`, so there is no established detailed convention. Use short, imperative commit subjects such as `add controller command checks` or `document redis preflight`.

Pull requests should include a summary, local commands run, affected environment variables or services, and relevant MQTT/MongoDB/Redis logs. Link related issues when available.

## Security & Configuration Tips

Do not commit real MQTT passwords, API tokens, MongoDB credentials, or Redis URLs. Keep secrets in environment variables. Defaults in the README are for local development only.
