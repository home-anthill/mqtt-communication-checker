# Repository Guidelines

## Project Structure & Module Organization

This is a Poetry-managed Python utility for local MQTT communication checks.

- `src/__main__.py` contains the CLI implementation: preflight checks, MQTT publishing, MongoDB/Redis verification, and controller command checks.
- `src/__init__.py` marks the package used by Poetry.
- `check_mqtt_communication.py` is a thin compatibility runner that calls `src.__main__.main()`.
- `README.md` documents runtime services and environment variables.
- `.github/workflows/build.yml` installs the project with Poetry in CI.

There is no `tests/` directory yet. Add one with automated tests.

## Build, Test, and Development Commands

- `poetry install` installs runtime dependencies from `pyproject.toml` and `poetry.lock`.
- `poetry run mqtt-communication-checker` runs the installed console script.
- `poetry run python check_mqtt_communication.py` runs the compatibility entry point.
- `poetry build` creates distributable package artifacts.

The checker expects Mosquitto, MongoDB, RabbitMQ, Redis, `producer`, `consumer`, and optionally `online-receiver`. Use environment overrides from `README.md`, for example:

```bash
MQTT_HOST=localhost MONGO_URI=mongodb://localhost:27017 poetry run mqtt-communication-checker
```

## Coding Style & Naming Conventions

Use Python 3.12-compatible code. Follow PEP 8 with 4-space indentation, `snake_case` functions and variables, and uppercase constants such as `POLL_SECONDS`. Keep helpers small and explicit; prefer the standard library plus existing dependencies over new packages.

No formatter or linter is configured. If adding one, wire it into Poetry and CI in the same change.

## Testing Guidelines

No automated test framework is currently configured. For new tests, prefer `pytest` under `tests/`, with files named `test_*.py`. Unit-test pure helpers such as signature builders, URI parsing, value matching, and polling behavior with mocks.

Run future tests with:

```bash
poetry run pytest
```

For manual verification, run the CLI against the local stack and confirm it exits nonzero on failed preflight or verification checks.

## Commit & Pull Request Guidelines

Git history currently contains only `first commit`, so there is no established detailed convention. Use short, imperative commit subjects such as `add controller command checks` or `document redis preflight`.

Pull requests should include a summary, local commands run, affected environment variables or services, and relevant MQTT/MongoDB/Redis logs. Link related issues when available.

## Security & Configuration Tips

Do not commit real MQTT passwords, API tokens, MongoDB credentials, or Redis URLs. Keep secrets in environment variables. Defaults in the README are for local development only.
