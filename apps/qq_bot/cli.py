"""Explicit QQ networking opt-in and separately approved read-only Monitoring data."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict, replace
from datetime import datetime, timezone
import getpass
import importlib.util
from pathlib import Path
import sys
import tempfile
import warnings

from apps.ai_backend import secure_files
from .adapter import QQAdapter
from .configuration import app_identifier, load_access, save_secret, secret_supplier
from .contracts import BotError
from .gateway import QQGateway, audit
from .service import ReadOnlyQueries
from .transport import GatewayURLRejected, QQAPI


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if '--offline-demo' in arguments:
        from .offline import main as offline_main
        return offline_main(arguments)
    parser = argparse.ArgumentParser(description='BOT-1B QQ read-only experimental transport; never uses an LLM')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--configure-secret', action='store_true', help='Hidden prompt; existing private CredentialStore')
    mode.add_argument('--check-config', action='store_true', help='Read access configuration only; no credential or network I/O')
    mode.add_argument('--check-monitoring', action='store_true', help='Explicit read-only instance preflight; no QQ or credentials')
    mode.add_argument('--check-ai-readiness', action='store_true', help='Maintained candidate only; no credentials, data or network')
    mode.add_argument('--discover', action='store_true', help='Show QQ group/member OpenIDs locally; never replies or queries data')
    mode.add_argument('--connect', action='store_true', help='Connect official WSS and reply to allowed @messages')
    parser.add_argument('--replace-secret', action='store_true', help='Explicit replacement, only with --configure-secret')
    parser.add_argument('--access-file', type=Path)
    parser.add_argument('--app-id')
    data = parser.add_mutually_exclusive_group()
    data.add_argument('--help-only', action='store_true')
    data.add_argument('--fictional-data', action='store_true')
    data.add_argument('--monitoring-config', type=Path, help='Explicit approved local instance/device configuration')
    parser.add_argument('--confirm-qq-network', action='store_true')
    parser.add_argument('--run-seconds', type=int, default=600, help='Finite session, 1..3600 seconds')
    args = parser.parse_args(arguments)
    if args.check_ai_readiness:
        if (args.access_file or args.app_id or args.help_only or args.fictional_data or args.monitoring_config
                or args.confirm_qq_network or args.replace_secret):
            parser.error('AI_READINESS_ACCEPTS_NO_DATA_OR_NETWORK_OPTIONS')
        try:
            import json
            from .ai_preflight import readiness_report
            print(json.dumps(readiness_report(),ensure_ascii=False),flush=True)
            return 0  # A valid BLOCKED preparation, not permission for real execution.
        except Exception:
            audit('QQ_AI_SCOPE_REVIEW_REQUIRED');return 1
    if not 1 <= args.run_seconds <= 3600:
        parser.error('INVALID_RUN_DURATION')
    if args.replace_secret and not args.configure_secret:
        parser.error('REPLACE_REQUIRES_CONFIGURE')
    if (args.discover or args.connect) and not args.confirm_qq_network:
        parser.error('QQ_NETWORK_CONFIRMATION_REQUIRED')
    if args.connect and not (args.help_only or args.fictional_data or args.monitoring_config):
        parser.error('EXPLICIT_DATA_MODE_REQUIRED')
    if (args.connect or args.check_config or args.check_monitoring) and args.access_file is None:
        parser.error('ACCESS_FILE_REQUIRED')
    if args.check_monitoring and not args.monitoring_config:
        parser.error('MONITORING_CONFIG_REQUIRED')
    if args.discover and (not args.app_id or args.access_file or args.help_only or args.fictional_data or args.monitoring_config):
        parser.error('DISCOVERY_REQUIRES_APP_ID_ONLY')
    if args.configure_secret and (args.access_file or args.app_id or args.help_only or args.fictional_data or args.monitoring_config):
        parser.error('CONFIGURE_ACCEPTS_NO_DATA_OPTIONS')
    root = Path(__file__).resolve().parents[2]
    try:
        if not (root/'pyproject.toml').is_file():
            raise BotError('SOURCE_WORKSPACE_REQUIRED')
        if args.configure_secret:
            if not sys.stdin.isatty():
                raise BotError('INTERACTIVE_SECRET_PROMPT_REQUIRED')
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                value = getpass.getpass('QQ AppSecret（隐藏输入，不调用模型或QQ）：')
            save_secret(root, value, replace=args.replace_secret)
            audit('QQ_SECRET_SAVED')
            return 0
        config = load_access(args.access_file) if args.access_file else None
        source_config = None
        if args.monitoring_config:
            from .monitoring_source import load_monitoring_config
            source_config = load_monitoring_config(args.monitoring_config)
            source_config.check_bindings(config)
        if args.check_config:
            audit('QQ_ACCESS_CONFIG_VALID', count=len(config.groups))
            return 0
        if args.check_monitoring:
            from .monitoring_source import InstanceMonitoring
            InstanceMonitoring(source_config)
            audit('QQ_MONITORING_READ_ONLY_READY', count=len(source_config.devices))
            return 0
        if importlib.util.find_spec('websockets') is None:
            raise BotError('QQ_WEBSOCKETS_DEPENDENCY_MISSING')
        with ExitStack() as resources:
            app_id = app_identifier(args.app_id) if args.discover else config.app_id
            if args.discover:
                def discovered(group, member):
                    import json
                    # Explicit discovery output is for local access configuration, never message bodies.
                    print(json.dumps({'discovery_only': True, 'group_openid': group,
                                      'member_openid': member}), flush=True)
                adapter, discover = None, discovered
            else:
                discover = None
                if args.help_only:
                    config = replace(config, groups=tuple(replace(g, capabilities=()) for g in config.groups))
                    queries = ReadOnlyQueries(None, None, live=True)
                elif source_config is not None:
                    from .monitoring_source import InstanceMonitoring
                    monitoring = InstanceMonitoring(source_config)
                    config = replace(config, groups=tuple(replace(g, capabilities=tuple(
                        c for c in g.capabilities if c != 'knowledge')) for g in config.groups))
                    queries = ReadOnlyQueries(monitoring, None, live=True, instance_id=source_config.instance_id)
                else:
                    if any(g.device_id not in ('sim-pond-1', 'sim-pond-2') for g in config.groups):
                        raise BotError('UNKNOWN_FICTIONAL_DEVICE')
                    from .offline import seed_fictional
                    parent = root/'outputs/test-tmp'
                    parent.mkdir(parents=True, exist_ok=True)
                    temporary = resources.enter_context(tempfile.TemporaryDirectory(prefix='bot1b-', dir=parent))
                    monitoring, knowledge = seed_fictional(temporary, lambda: datetime.now(timezone.utc))
                    queries = ReadOnlyQueries(monitoring, knowledge, live=True)
                adapter = QQAdapter(config, queries, mode='QQ_PASSIVE_READY')
            api = QQAPI(app_id, secret_supplier(root))
            resources.callback(api.close)
            gateway = QQGateway(app_id, api, adapter, discover=discover)
            gateway.run(args.run_seconds)
        return 0
    except KeyboardInterrupt:
        audit('QQ_CANCELLED')
        return 0
    except secure_files.SecureFileError:
        audit('ENV_PERMISSION_ERROR')
        return 1
    except Exception as error:
        if isinstance(error, GatewayURLRejected):
            diagnostic = asdict(error.diagnostic)
            audit(diagnostic.pop('reason_code'), **diagnostic)
        code = getattr(error, 'code', None)
        audit(code if isinstance(code, str) else 'QQ_START_FAILED')
        return 1
