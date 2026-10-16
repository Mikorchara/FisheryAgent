import argparse
import os
from pathlib import Path

from .app import create_app


def project_root(*, module_file=None, working_directory=None):
    """Preserve repository identity when imported from a wheel installation."""
    source = Path(module_file or __file__).resolve().parents[2]
    if (source / 'pyproject.toml').is_file():
        return source
    workspace = Path(working_directory).resolve() if working_directory is not None else Path.cwd().resolve()
    if not (workspace / 'pyproject.toml').is_file() or not (workspace / 'apps').is_dir():
        raise ValueError('WORKSPACE_REQUIRED')
    return workspace


def main():
    parser = argparse.ArgumentParser(description="Fishery management Web (local monitoring, optional Assistant)")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--enable-ingestion", action="store_true", help="Local simulator writes, token required")
    parser.add_argument("--legacy-demo", action="store_true", help="Isolated R1 static Demo; no ingestion")
    parser.add_argument("--enable-assistant", action="store_true", help="Enable Normal Assistant; each Send requires network confirmation")
    parser.add_argument("--assistant-multi-round-trial", action="store_true", help="Management-only Normal local trial; exact Scope/Policy required")
    parser.add_argument("--assistant-streaming-trial", action="store_true", help="Qwen two-tool Streaming local trial; exact Scope/Policy required")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.legacy_demo and args.enable_ingestion:
        parser.error("LEGACY_DEMO_CANNOT_INGEST")
    if args.legacy_demo and args.enable_assistant:
        parser.error("ASSISTANT_REQUIRES_MONITORING_SERVICE")
    if args.assistant_multi_round_trial and not args.enable_assistant:
        parser.error("MULTI_ROUND_TRIAL_REQUIRES_ASSISTANT")
    if args.assistant_streaming_trial and not args.enable_assistant:
        parser.error("STREAMING_TRIAL_REQUIRES_ASSISTANT")
    data_service, token = None, None
    if not args.legacy_demo:
        try:
            root = project_root()
        except ValueError:
            parser.error('WORKSPACE_REQUIRED')
        from apps.monitoring.repository import MonitoringRepository
        from apps.monitoring.service import MonitoringService
        from apps.monitoring.contracts import valid_token
        if args.enable_ingestion:
            token = os.environ.get("FISHERY_SIM_INGEST_TOKEN", "")
            if not valid_token(token):
                parser.error("INGESTION_TOKEN_REQUIRED: set a 32-128 character alphanumeric development token")
        path = root/"outputs"/"management_web"/"monitoring.sqlite3"
        data_service = MonitoringService(MonitoringRepository(path))
    ai_options = {}
    if args.enable_assistant:
        from .ai_adapter import ManagementAssistant
        from apps.ai_backend.credential_paths import CredentialLocationError
        from apps.ai_backend.credentials import CredentialFileError
        from apps.ai_backend.tools.policy import ToolPolicyError
        from apps.ai_backend.model_gateway import GatewayError
        try:
            ai_options["ai"] = ManagementAssistant.local(data_service, root,
                multi_round_trial=args.assistant_multi_round_trial,
                streaming_trial=args.assistant_streaming_trial)
        except (CredentialLocationError, CredentialFileError, ToolPolicyError, GatewayError):
            parser.error("AI_CONFIGURATION_UNAVAILABLE")
    app = create_app(allowed_hosts=(f"127.0.0.1:{args.port}", f"localhost:{args.port}"),
                     data_service=data_service, ingestion_token=token, **ai_options)
    print(f"Management Web · Local: http://127.0.0.1:{args.port}", flush=True)
    app.run(host="127.0.0.1", port=args.port, debug=False, load_dotenv=False)


if __name__ == "__main__":
    main()
