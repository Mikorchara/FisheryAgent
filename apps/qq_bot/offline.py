"""Fictional fixtures and finite in-memory transport demo; never opens a real instance."""
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from apps.knowledge.repository import KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from .adapter import OfflineQQAdapter
from .contracts import BotConfig, GroupAccess
from .service import ReadOnlyQueries

APP_ID = 'offline-fishery'
GROUP = 'fictional-group'
MEMBER = 'fictional-member'


@contextmanager
def network_blocked():
    """Local guard, not a network sandbox. All four socket entry points fail closed."""
    with ExitStack() as stack:
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.socket.sendto', 'socket.getaddrinfo'):
            stack.enter_context(patch(target, side_effect=RuntimeError('BOT_OFFLINE_NETWORK_FORBIDDEN')))
        yield


def packet(content, now, *, msg_id='fixture-message', group=GROUP, member=MEMBER):
    return json.dumps({'op': 0, 't': 'GROUP_AT_MESSAGE_CREATE', 's': 1,
        'd': {'id': msg_id, 'group_openid': group, 'author': {'member_openid': member, 'bot': False},
              'timestamp': now.isoformat(), 'content': content}}, ensure_ascii=False).encode('utf-8')


def seed_fictional(directory, clock):
    """New temporary files only; callers own the directory, no source-data copying."""
    directory = Path(directory)
    if not directory.is_dir() or any(directory.iterdir()):
        raise ValueError('EMPTY_TEMPORARY_DIRECTORY_REQUIRED')
    monitoring = MonitoringService(MonitoringRepository(directory/'monitoring.sqlite3'),
        device_names={'sim-pond-1': '虚构低氧池', 'sim-pond-2': '虚构正常池'}, clock=clock)
    end = clock()
    for index, oxygen in ((1, 2.2), (2, 6.4)):
        sim = Simulator(start=end-timedelta(seconds=30), seed=42, device_id=f'sim-pond-{index}',
                        session_id=f'bot-offline-{index}')
        for _ in range(3):
            batch = sim.advance()
            for key in ('mean', 'min', 'max', 'latest'):
                batch['water']['metrics']['dissolved_oxygen_mg_l'][key] = oxygen
            monitoring.ingest(batch)
    knowledge = KnowledgeContentService(KnowledgeRepository(directory/'knowledge.sqlite3'), clock=clock)
    knowledge.create({'title': '离线示例：溶解氧观察', 'category': 'water_quality',
        'body': '虚构学习资料：溶解氧下降时先检查观测质量与设备状态。此文本不是现场诊断或处置指令。'})
    return monitoring, knowledge


def demo(commands=None):
    root = Path(__file__).resolve().parents[2]
    if not (root/'pyproject.toml').is_file():
        raise ValueError('SOURCE_WORKSPACE_REQUIRED')
    parent = root/'outputs/test-tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with network_blocked(), tempfile.TemporaryDirectory(prefix='bot1a-', dir=parent) as temporary:
        now = datetime(2026, 10, 24, 4, 0, tzinfo=timezone.utc)
        monitoring, knowledge = seed_fictional(temporary, lambda: now)
        config = BotConfig(APP_ID, (GroupAccess(GROUP, 'sim-pond-1', (MEMBER,),
                                               ('current', 'history', 'knowledge', 'events')),))
        adapter = OfflineQQAdapter(config, ReadOnlyQueries(monitoring, knowledge), clock=lambda: now)
        print('BOT-1A · 离线虚构数据 · QQ 与 Provider 请求均为 0 · 不读取真实实例/凭据')
        examples = commands or ('/帮助', '/当前水质', '/历史水质 10', '/知识 溶解氧', '/当前异常', '/问AI 分析水质')
        for index, command in enumerate(examples):
            result = adapter.receive(packet(command, now, msg_id=f'demo-{index}'), transport_app_id=APP_ID)
            print(json.dumps(asdict(result), ensure_ascii=False))
        duplicate = adapter.receive(packet(examples[0], now, msg_id='demo-0'), transport_app_id=APP_ID)
        denied = adapter.receive(packet('/当前水质', now, group='unknown-group'), transport_app_id=APP_ID)
        print(json.dumps({'duplicate': duplicate.code, 'unauthorized_group': denied.code,
                          'mode': 'OFFLINE_NOT_SENT', 'temporary_databases_removed_on_exit': True}, ensure_ascii=False))


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='BOT-1A offline prototype; no live transport or AI')
    parser.add_argument('--offline-demo', action='store_true', help='Run finite fictional examples in temporary SQLite')
    parser.add_argument('--command', action='append', help='Try a command against fictional data only (up to six)')
    args = parser.parse_args(argv)
    if not args.offline_demo:
        parser.error('OFFLINE_DEMO_REQUIRED: only --offline-demo is supported')
    if args.command and len(args.command) > 6:
        parser.error('AT_MOST_SIX_OFFLINE_COMMANDS')
    try:
        demo(args.command)
    except Exception:
        parser.exit(1, 'BOT_OFFLINE_DEMO_FAILED\n')
    return 0
