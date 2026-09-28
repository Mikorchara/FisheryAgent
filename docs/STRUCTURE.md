# Project Structure

```text
Fishery_AI_Prototype/
├─ README.md
├─ AGENTS.md
├─ pyproject.toml
├─ src/fishery_ai/
│  ├─ contracts.py
│  ├─ domain.py
│  ├─ repositories.py
│  ├─ knowledge.py
│  ├─ model_gateway.py
│  ├─ openai_compatible_adapter.py
│  ├─ application.py
│  ├─ observability.py
│  ├─ composition.py
│  ├─ __main__.py
│  └─ resources/{knowledge,mock}/
├─ tests/
├─ scripts/
└─ docs/
   └─ deep-dive/
```

- `contracts.py`: immutable water-quality, detection, evidence, request, and result contracts.
- `domain.py`: deterministic water-quality findings.
- `repositories.py`: fixed Mock sensor and detection inputs.
- `knowledge.py`: TF-IDF retrieval and evidence construction.
- `model_gateway.py`: profiles, runtime snapshots, gateway contract, and `MockGateway`.
- `openai_compatible_adapter.py`: SDK-based OpenAI-compatible transport and streaming.
- `application.py`: fixed Chat/Advice orchestration and model-output parsing.
- `observability.py`: allowlisted JSONL traces.
- `composition.py` and `__main__.py`: offline component wiring and CLI entry point.
- `resources/`: packaged knowledge snapshot, provenance note, profiles, and Mock scenarios.
- `tests/`: offline contract, gateway, orchestration, and trace checks.
- `scripts/`: source-checkout Mock Demo entry point.
- `docs/`: user-facing guides; `docs/deep-dive/` holds detailed historical reports.

The project currently has no Agent, Tool Calling, Memory, or real-model deployment module.
