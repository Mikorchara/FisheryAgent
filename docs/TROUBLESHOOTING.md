# Troubleshooting and Known Limits

| Area | Current state and first check |
| --- | --- |
| Real OpenAI-compatible services | No real service has been verified. The Mock Demo uses `MockGateway` even when a Cloud or Local profile is selected. Verify a chosen endpoint separately on the target workstation. |
| Local model deployment | No model is downloaded or started by this project. Confirm the local server, model ID, and compatible endpoint before a real connection test. |
| Streaming | Compatibility depends on the server's Chat Completions stream implementation. The SDK adapter and retry boundary have only offline fake-client coverage so far. |
| Knowledge provenance | The packaged legacy JSON lacks per-chunk publication metadata. See [source notes](../src/fishery_ai/resources/knowledge/SOURCE.md). |
| Dependency versions | `pyproject.toml` declares version ranges; a lock-file strategy is not yet decided. Use a virtual environment and review the installed versions when reproducing a result. |

For setup and offline commands, see [Build and Run](BUILD_RUN.md).
