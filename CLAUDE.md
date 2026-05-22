# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

Dependency management is via Poetry; Python 3.11+ is required.

- Install for development (runtime + CPU backend + CLI + dev tools):
  `poetry install --with dev --extras "cpu cli"`
- Run the full pytest suite (image regression tests):
  `poetry run pytest`
- Run a single test:
  `poetry run pytest tests/test_remove.py::<test_name>`
- Format / lint (matches the bandit + black + isort CI checks in `.github/`):
  - `poetry run black --force-exclude rembg/_version.py ./rembg`
  - `poetry run isort --profile black ./rembg`
  - `poetry run flake8 ./rembg`
  - `poetry run mypy ./rembg`
- Build distributable artifacts: `poetry build`
- Smoke-test the CLI entry point: `poetry run rembg --help`

Extras toggle the ONNX Runtime backend: `cpu` (onnxruntime), `gpu` (CUDA, non-darwin), `rocm` (Linux), and `cli` (FastAPI/Click/Gradio server + CLI deps). Pick the right extra for the platform you are testing on — installing `gpu` on macOS will fail by design.

## Architecture

`rembg` is a thin orchestration layer around a registry of ONNX-Runtime "sessions", one per model.

- **Pipeline entry point** — `rembg/bg.py::remove` accepts `bytes | PIL.Image | np.ndarray`, normalizes orientation, calls `session.predict(img)` to get one or more masks, then composites the cutout via one of `alpha_matting_cutout`, `putalpha_cutout`, or `naive_cutout`. When a session returns multiple masks (e.g. cloth-seg), they are concatenated vertically by `get_concat_v_multi`. `post_process` and `apply_background_color` are optional post-steps. The function returns `bytes`, `PIL.Image`, or `np.ndarray` mirroring the input type unless `force_return_bytes=True`.
- **Session registry** — `rembg/sessions/__init__.py` imports each session class and registers it in the `sessions` dict keyed by `Cls.name()`. `session_factory.new_session(name, ...)` looks up the class and instantiates it. Adding a new model means: implement a subclass of `BaseSession` (override `predict`, `download_models`, and `name`), then import + register it in `sessions/__init__.py`. The default model when `session=None` is `u2net`.
- **BaseSession** (`rembg/sessions/base.py`) — owns provider selection (CUDA → ROCm → CPU based on `onnxruntime.get_device()` and available providers, overridable via `providers=` kwarg), the model cache directory (`U2NET_HOME` / `XDG_DATA_HOME/.u2net`), and the optional `MODEL_CHECKSUM_DISABLED` escape hatch. Models are fetched lazily via `pooch` inside each session's `download_models` classmethod. `bg.download_models()` exposes a way to pre-download.
- **CLI** — `rembg/cli.py` exposes a Click group; `rembg/commands/*_command.py` registers subcommands: `i` (single file), `p` (folder), `b` (stdin/stream bytes), `s` (FastAPI + Uvicorn HTTP server, optional Gradio UI), `d` (download models). The Click group is wired in `commands/__init__.py` via `command_functions`. `cli.py` has a fast-path for `--version` that avoids importing onnxruntime.
- **Custom-model sessions** — `u2net_custom`, `dis_custom`, `ben_custom` accept a user-supplied model path. Treat that path (and any URL/model option flowing from the CLI or HTTP server) as untrusted: prior CVEs in this repo were path traversal in custom sessions (GHSA-3wqj-33cg-xc48) and SSRF/CORS in the HTTP server (GHSA-55v6-g8pm-pw4c). Preserve those validations when refactoring `s_command.py` or the `*_custom.py` sessions.

## Testing notes

`tests/test_remove.py` validates outputs against `tests/fixtures/` inputs and `tests/results/` reference images using perceptual hashes (`imagehash`). Running the suite downloads ONNX model weights on first use — keep the cache warm between runs. When a behavior change legitimately shifts model output, regenerate the reference images in `tests/results/` and visually diff before committing.

## Conventions

- Python 3.11+, 4-space indentation (see `.editorconfig`). Black + isort (`--profile black`) are authoritative; prefer type annotations on new public functions.
- Command modules follow the `<letter>_command.py` naming and export a `<letter>_command` Click command. Session modules are named after the model id used as `Cls.name()` (e.g. `birefnet_general.py` → `"birefnet-general"`).
- Version is managed by `poetry-dynamic-versioning` from git tags (`vX.Y.Z`) and substituted into `rembg/__init__.py`; do not hand-edit `_version.py` or the `version =` field in `pyproject.toml`.
