# Worker Setup

This worker depends on the local `quant-core` package in `../../core`.

## Local development (pip)

From repository root:

```bash
pip install -e ./core
pip install -e ./services/worker
python -c "import quant_core.pipeline; print('ok')"
```

Or from `services/worker`:

```bash
pip install -e ../../core
pip install -e .
python -c "import quant_core.pipeline; print('ok')"
```

Notes:
- `quant-core` is declared in `services/worker/pyproject.toml` as a package dependency.
- Editable install of `core` is required so imports resolve in monorepo development.
