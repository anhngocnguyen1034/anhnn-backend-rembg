# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python package for background removal. Core source code lives in `rembg/`: `bg.py` contains image removal logic, `cli.py` defines the CLI entry point, `commands/` holds subcommands, and `sessions/` contains model-specific session classes. Tests live in `tests/`, with image inputs in `tests/fixtures/` and expected outputs in `tests/results/`. User documentation is in `README.md` and `USAGE.md`; packaging and dependency metadata are in `pyproject.toml`.

## Build, Test, and Development Commands

- `poetry install --with dev --extras "cpu cli"` installs runtime, CLI, CPU backend, and development tools.
- `poetry run pytest` runs the image regression test suite.
- `poetry run rembg --help` checks the installed CLI entry point.
- `poetry run black --force-exclude rembg/_version.py ./rembg` formats source files.
- `poetry run isort --profile black ./rembg` sorts imports using Black-compatible rules.
- `poetry build` creates distributable package artifacts.

## Coding Style & Naming Conventions

Use Python 3.11+ and 4-space indentation, matching `.editorconfig`. Keep source formatted with Black and imports ordered by isort. Prefer type annotations for new public functions and keep mypy-friendly signatures where practical. Name command modules with the existing pattern, such as `i_command.py` or `s_command.py`; name session modules after their model identifier, such as `u2net.py` or `birefnet_general.py`.

## Testing Guidelines

Pytest is the test runner. Add tests under `tests/` using `test_*.py` names. Image behavior is validated with perceptual hashes against files in `tests/results/`; when model output intentionally changes, regenerate expected images and inspect the visual difference before committing. Running tests may download model assets, so prefer a prepared local model cache for repeat runs.

## Commit & Pull Request Guidelines

Recent commits use short, imperative summaries such as `Fix black formatting in s_command.py` or `Add --no-ui flag to server command`. Keep the first line focused on the behavior changed; include issue or advisory references when relevant. Pull requests should describe the change, list validation commands run, note model or fixture updates, and include CLI examples or screenshots for user-facing behavior.

## Security & Configuration Tips

Treat file paths, URLs, and custom model options as untrusted input, especially in CLI and server code. Review changes against the existing bandit CI command and avoid weakening checks around path traversal, SSRF, CORS, or model checksum behavior.
