# AGENTS.md — rules for any coding agent working on PulseTrader V4

Start of every session: read this file, read `knowledge.md`, inspect the repo, then continue from the
first incomplete phase listed in `knowledge.md`. Do not redo completed phases.

## Non-negotiables
- Real data only. Synthetic data is allowed solely as the golden test fixture (`ml/tests/golden.py`).
- Never modify `data/raw/`. Derived data goes to `data/{validated,canonical,features,labels,datasets}`.
- Chronological splits only, with purging/embargo. Never shuffle time series.
- The final test period is untouched until model development is finished. If it ever influences a
  decision, define a new untouched period and record that in `knowledge.md`.
- Fit scalers/imputers/feature selection on training data only (`Preprocessor.fit` enforces this).
- One feature engine (`ml/src/pulsetrader/features/engine.py`) for training and live. Never copy formulas.
- Report accuracy together with balanced accuracy, MCC and coverage. Never report a target number
  that was not measured. Selective-prediction results always state coverage.
- `MockProvider` is test-only.
- No `except: pass` / blind excepts (ruff rules BLE, S110 enforce this). Never commit secrets.

## Phase completion rule
A phase is complete only after: `ruff format`, `ruff check`, `mypy src`, `pytest`, relevant data/ML
runs, and build all pass, and results are written to `knowledge.md`.

## Commands (from `ml/`)
```
python -m venv .venv && .venv/bin/pip install -e ".[dev,serve,fetch]"
.venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src && .venv/bin/pytest
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader fetch      # needs huggingface.co network access
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader discover   # Phase 1 -> reports/
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader pipeline   # Phase 2 -> data/canonical + reports/
```
