# Build and Run

## Requirements

- Python 3.11 or newer.
- A Windows PowerShell session in the repository root.

## Windows setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -e .
```

If PowerShell does not resolve the extensionless activation command, use `.\.venv\Scripts\Activate.ps1`. You can also call `.\.venv\Scripts\python.exe` directly without activating the environment.

`pyproject.toml` declares the runtime dependencies: the official `openai` SDK and `httpx` for timeout configuration. The default TF-IDF implementation uses Python only. `scikit-learn` is optional for the alternative retrieval backend; it is not needed for the default workflow or tests. No separate `requirements.txt` is maintained.

## Offline tests

```powershell
python -m unittest discover -s tests -v
```

Tests use fake SDK clients and block socket connections. They do not use real API keys, call real APIs, or start models.

## Mock Demo

```powershell
python -m fishery_ai demo
python -m fishery_ai demo --profile local-demo --scenario partial_stale
```

Both profile choices run through `MockGateway`; the Demo does not call a Cloud or local model. It writes JSONL traces under `outputs/` in the current working directory.
