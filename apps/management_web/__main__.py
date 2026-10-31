import argparse
import os
from pathlib import Path

from .app import create_app
from apps.management_paths import ManagementPaths


def knowledge_content(root, *, data_paths=None):
    from apps.knowledge.repository import KnowledgeRepository
    from apps.knowledge.service import KnowledgeContentService
    paths = data_paths if data_paths is not None else ManagementPaths.resolve(root)
    return KnowledgeContentService(KnowledgeRepository(paths.knowledge,require_existing=True))


def project_root(*, module_file=None, working_directory=None):
    """Preserve repository identity when imported from a wheel installation."""
    source = Path(module_file or __file__).resolve().parents[2]
    if (source / 'pyproject.toml').is_file():
        return source
    workspace = Path(working_directory).resolve() if working_directory is not None else Path.cwd().resolve()
    if not (workspace / 'pyproject.toml').is_file() or not (workspace / 'apps').is_dir():
        raise ValueError('WORKSPACE_REQUIRED')
    return workspace


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fishery management Web (local monitoring, optional Assistant)")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument('--demo-video',type=Path,help='Explicit local MP4 demonstration, never observation evidence')
    parser.add_argument('--simulation-mode',choices=('full','water-only'),default='full')
    parser.add_argument('--device-report-directory',type=Path)
    parser.add_argument('--device-report-device-id')
    locations = parser.add_mutually_exclusive_group()
    locations.add_argument('--data-root', type=Path, help='Explicit existing management instance; no workspace fallback')
    locations.add_argument('--user-data', action='store_true', help='Use LOCALAPPDATA/FisheryManagement; explicit opt-in')
    parser.add_argument('--init-data', action='store_true', help='Create a NEW empty instance, then exit; never migrate')
    parser.add_argument('--project-root', type=Path, help='Stable project identity for installed-wheel startup; credentials unchanged')
    parser.add_argument("--enable-ingestion", action="store_true", help="Local simulator writes, token required")
    parser.add_argument("--legacy-demo", action="store_true", help="Isolated R1 static Demo; no ingestion")
    parser.add_argument("--enable-assistant", action="store_true", help="Enable Normal Assistant; each Send requires network confirmation")
    parser.add_argument("--assistant-multi-round-trial", action="store_true", help="Management-only Normal local trial; exact Scope/Policy required")
    parser.add_argument("--assistant-streaming-trial", action="store_true", help="Qwen two-tool Streaming local trial; exact Scope/Policy required")
    parser.add_argument("--assistant-history-trial", action="store_true", help="Qwen Normal history-only local trial; exact Scope/Policy required")
    parser.add_argument('--assistant-tools-trial',action='store_true',help='Qwen three-Tool local trial; also enable desired Normal/Streaming trial')
    args = parser.parse_args(argv)
    try:
        root = args.project_root.resolve() if args.project_root is not None else project_root()
        if not root.is_dir():
            raise ValueError('WORKSPACE_REQUIRED')
        paths = ManagementPaths.resolve(root, data_root=args.data_root, user_data=args.user_data)
    except ValueError as error:
        parser.error(str(error))
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    report_store=None
    if args.device_report_directory is not None or args.device_report_device_id is not None:
        if args.simulation_mode!='water-only' or not args.device_report_directory or not args.device_report_device_id:
            parser.error('DEVICE_REPORT_BINDING_REQUIRED')
        from apps.device_reports.storage import ReportStore
        from apps.device_reports.contracts import ReportError
        try:report_store=ReportStore(args.device_report_directory,read_only=True)
        except ReportError as error:parser.error(error.code)
    demo_video = None
    if args.demo_video is not None:
        from .demo_video import LocalDemoVideo
        try: demo_video = LocalDemoVideo.open(args.demo_video)
        except ValueError as error: parser.error(str(error))
    if args.legacy_demo and args.enable_ingestion:
        parser.error("LEGACY_DEMO_CANNOT_INGEST")
    if args.legacy_demo and args.enable_assistant:
        parser.error("ASSISTANT_REQUIRES_MONITORING_SERVICE")
    if args.assistant_multi_round_trial and not args.enable_assistant:
        parser.error("MULTI_ROUND_TRIAL_REQUIRES_ASSISTANT")
    if args.assistant_streaming_trial and not args.enable_assistant:
        parser.error("STREAMING_TRIAL_REQUIRES_ASSISTANT")
    if args.assistant_history_trial and not args.enable_assistant:
        parser.error("HISTORY_TRIAL_REQUIRES_ASSISTANT")
    if args.assistant_tools_trial and (not args.enable_assistant or not (
            args.assistant_multi_round_trial or args.assistant_streaming_trial)):
        parser.error('TOOLS_TRIAL_REQUIRES_ASSISTANT_AND_TRANSPORT_TRIAL')
    from .instance import initialize_instance, validate_instance, InstanceError
    if (args.data_root is not None or args.user_data) and args.legacy_demo:
        parser.error('LEGACY_DEMO_CANNOT_USE_DATA_ROOT')
    if args.init_data:
        try:
            initialize_instance(paths)
        except InstanceError as error:
            parser.error(error.code)
        print('MANAGEMENT_INSTANCE_INITIALIZED: empty Monitoring and Knowledge; no user data migrated.')
        return
    if paths.data_root is not None and not args.legacy_demo:
        try:
            validate_instance(paths)
        except InstanceError as error:
            if error.code == 'MONITORING_DATABASE_UPGRADE_REQUIRED':
                parser.error(error.code+': 请先停止写入、备份，并显式执行 apps/monitoring/migrate.py；不要重新初始化旧实例。')
            parser.error(error.code+': 请核对实例路径；新实例须显式使用 --init-data，已有数据须先迁移。')
    data_service, token = None, None
    if not args.legacy_demo:
        from apps.monitoring.repository import MonitoringRepository
        from apps.monitoring.service import MonitoringService
        from apps.monitoring.contracts import valid_token
        if args.enable_ingestion:
            token = os.environ.get("FISHERY_SIM_INGEST_TOKEN", "")
            if not valid_token(token):
                parser.error("INGESTION_TOKEN_REQUIRED: set a 32-128 character alphanumeric development token")
        # The legacy mode retains its development auto-create contract. Explicit
        # instances use rw (not rwc), including subsequent Repository connections.
        try:
            data_service = MonitoringService(MonitoringRepository(paths.monitoring,
                **({'require_existing':True} if paths.data_root is not None else {})))
        except ValueError as error:
            if str(error) == 'MONITORING_SCHEMA_UPGRADE_REQUIRED':
                parser.error(str(error)+': 请先停止写入、备份，并显式执行 apps/monitoring/migrate.py；不会自动升级旧库。')
            raise
    from apps.knowledge.repository import KnowledgeError
    try:
        knowledge = knowledge_content(root, **({'data_paths':paths} if paths.data_root is not None else {}))
    except KnowledgeError as error:
        parser.error(error.code+': 请先按 apps/docs/deep-dive/KNOWLEDGE_CONTENT.md 完成显式知识库迁移。')
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
                streaming_trial=args.assistant_streaming_trial,
                history_trial=args.assistant_history_trial,unified_tools_trial=args.assistant_tools_trial,knowledge=knowledge,
                **({'data_paths':paths} if paths.data_root is not None else {}))
        except (CredentialLocationError, CredentialFileError, ToolPolicyError, GatewayError):
            parser.error("AI_CONFIGURATION_UNAVAILABLE")
    settings = None
    if args.enable_assistant:
        from apps.ai_service.settings import ManagementSettingsService
        settings = ManagementSettingsService(ai_options['ai'].backend, paths.settings)
    if demo_video is not None: ai_options['demo_video'] = demo_video
    if args.simulation_mode!='full':
        ai_options.update(simulation_mode=args.simulation_mode,device_report_store=report_store,
                          device_report_device_id=args.device_report_device_id)
    app = create_app(allowed_hosts=(f"127.0.0.1:{args.port}", f"localhost:{args.port}"),
                     data_service=data_service, ingestion_token=token, knowledge_service=knowledge,
                     settings_service=settings, **ai_options)
    print(f"Management Web · Local: http://127.0.0.1:{args.port}", flush=True)
    app.run(host="127.0.0.1", port=args.port, debug=False, load_dotenv=False)


if __name__ == "__main__":
    main()
