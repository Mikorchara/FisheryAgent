"""Fixed read-only commands. Reuse domain services, never model or write APIs."""
from apps.monitoring.contracts import METRICS
from apps.ai_service.business_tools.current_water_quality import project_water_tool
from apps.ai_service.business_tools.fishery_knowledge import validate_arguments, search_fishery_knowledge
from .contracts import BotError

HELP = ('BOT-1A 离线只读原型（未连接 QQ / AI）\n'
        '/当前水质\n/历史水质 10（也支持 30、60 分钟）\n/知识 关键词\n/当前异常\n/帮助\n'
        '群与设备由配置绑定；不支持 ACK、人工结束、删除或修改配置。')


def plain(value, limit=350):
    """Plain text only; neutralize mentions and terminal controls in stored text."""
    text = str(value).replace('@', '＠')
    text = ''.join(c for c in text if c.isprintable() or c == '\n')
    return text[:limit] + ('…' if len(text) > limit else '')


def _time(value):
    return plain(value or '无观测时间', 64)


class ReadOnlyQueries:
    """Capture read callables only. This facade is not a DB-level permission system."""
    def __init__(self, monitoring, knowledge, *, live=False, instance_id=None):
        self._instance_id = instance_id
        self._help = HELP if not live else HELP.replace(
            'BOT-1A 离线只读原型（未连接 QQ / AI）', 'BOT-1B QQ 只读实验（未启用 AI）')
        self._capture = monitoring.capture_water if monitoring is not None else None
        self._history = monitoring.query_water_history if monitoring is not None else None
        self._events = monitoring.event_cycles if monitoring is not None else None
        self._knowledge = knowledge
        if instance_id is not None:
            self._help = ('BOT-2B 指定实例只读查询（未启用 AI / Knowledge）\n'
                          '/当前水质\n/历史水质 10（也支持 30、60 分钟）\n/当前异常\n/帮助\n'
                          '实例和设备仅由本机配置绑定；不支持任何写操作。')

    def execute(self, message, access):
        pieces = message.content.lstrip('/').split(maxsplit=1)
        command, argument = pieces[0], pieces[1] if len(pieces) == 2 else ''
        capability = {'当前水质': 'current', '历史水质': 'history',
                      '知识': 'knowledge', '当前异常': 'events'}.get(command)
        if command.lower() in ('help', '帮助') and not argument:
            return 'OK', self._help
        if command in ('AI', '问AI'):
            return 'AI_DISABLED', 'BOT-1A 未启用 AI，也不会调用模型。请使用 /帮助 查看只读命令。'
        if capability is None:
            return 'UNSUPPORTED_COMMAND', '不支持此命令；仅提供只读查询，请输入 /帮助。'
        if capability not in access.capabilities:
            return 'CAPABILITY_DENIED', '此群尚未获准使用该查询能力。'
        if capability == 'knowledge' and self._instance_id is not None:
            return 'CAPABILITY_DENIED', '指定 Monitoring 实例模式未接入知识库。'
        device = access.device_id
        if capability == 'current' and not argument:
            return 'OK', self.current(device)
        if capability == 'history' and argument in ('10', '30', '60'):
            return 'OK', self.history(device, int(argument))
        if capability == 'knowledge' and argument:
            return 'OK', self.knowledge(argument)
        if capability == 'events' and not argument:
            return 'OK', self.events(device)
        return 'INVALID_ARGUMENTS', '参数不正确；历史查询仅支持 10/30/60 分钟，其他用法见 /帮助。'

    def current(self, device):
        capture = self._capture(device)
        facts = project_water_tool(capture)
        dq = facts['data_quality']
        lines = [f'当前水质 · {device} · {facts["source_kind"].upper()}',
                 f'观测：{_time(facts.get("water_quality", {}).get("observed_at") if facts["water_quality"] else None)}',
                 f'质量 {dq["quality"]} / 新鲜度 {dq["freshness"]} / 连接 {dq["connectivity"]}']
        for metric in capture.metrics:
            label = METRICS[metric.id][0]
            value = metric.mean if metric.quality == 'valid' else '数据不足'
            lines.append(f'{label}：{value} {metric.unit}（{metric.quality}）')
        lines.extend(plain(f['message']) for f in facts.get('findings', []) if f['state'] == 'HIT')
        lines.append('查询不等于重新采样；过期/缺测不能认定当前正常。')
        if self._instance_id:
            lines.insert(0, '只读实例：'+self._instance_id)
        return '\n'.join(lines)

    def history(self, device, minutes):
        value = self._history(device, lookback_minutes=minutes)
        lines = [f'历史水质 · {device} · SIMULATOR · 最近 {minutes} 分钟',
                 f'范围：{value["requested_range"]["start"]} → {value["requested_range"]["end"]}',
                 f'窗口 {value["counts"]["matching_windows"]} / 状态 {value["status"]}；留存完整性未知']
        for key, stat in value['metrics'].items():
            low, high = stat['min_window_mean'], stat['max_window_mean']
            interval = f'{low["value"]}～{high["value"]}' if low and high else '无可靠数据'
            lines.append(f'{METRICS[key][0]}：窗口均值范围 {interval} {stat["unit"]}；可靠窗口 {stat["reliable_windows"]}')
        lines.append('历史不代表当前；缺口/恢复/持续异常不在此命令中另作诊断。')
        if self._instance_id:
            lines.insert(0, '只读实例：'+self._instance_id)
        return '\n'.join(lines)

    def knowledge(self, query):
        try:
            arguments = validate_arguments({'query': query})
        except ValueError:
            raise BotError('INVALID_ARGUMENTS') from None
        value = search_fishery_knowledge(arguments, service=self._knowledge)
        lines = ['项目知识检索 · 背景资料，不是现场诊断']
        for hit in value['evidence'][:2]:
            lines.extend([f'来源：{plain(hit["source"], 140)} / 版本 {plain(hit["source_version"], 40)}',
                          f'Evidence：{plain(hit["id"], 140)}', plain(hit['text'])])
        if not value['evidence']:
            lines.append('未检索到匹配资料。')
        return '\n'.join(lines)

    def events(self, device):
        all_cycles = self._events(device_id=device)
        cycles = [e for e in all_cycles if e['device_id'] == device
                  and e.get('lifecycle_state') != 'RESOLVED' and e.get('status') != 'closed'
                  and not e.get('manual_end', {}).get('active')]
        lines = [f'当前异常 · {device} · SIMULATOR；{len(cycles)} 个未结束周期']
        ended = sum(bool(e.get('manual_end', {}).get('active')) for e in all_cycles)
        if ended:
            lines.append(f'{ended} 个人工结束周期未列入当前提醒；人工结束不代表规则恢复。')
        for event in cycles[:5]:
            state = ('状态待核实' if event['lifecycle_state'] != 'ACTIVE' else
                     '恢复观察中' if event.get('visual_recovery', {}).get('clear_count', 0) else '异常中')
            lines.append(f'{plain(event["title"], 100)} · {plain(event["severity"], 30)} · {state}')
            lines.append(f'最近观测：{_time(event.get("last_observed_at"))}')
        if len(cycles) > 5:
            lines.append('仅显示前 5 项，完整详情请在本机管理页面查看。')
        if not cycles:
            capture = self._capture(device)
            quality = capture.analysis.data_quality
            reliable = (quality.quality == 'valid' and quality.freshness == 'fresh'
                        and quality.connectivity == 'online')
            lines.append('列表未见需提醒周期；水质观测可靠，未据此推定视觉状态或规则恢复。' if reliable else
                         '状态未知：当前水质观测不足，不能认定正常。')
        lines.append('模拟规则信号不代表疾病确诊；人工知晓不代表规则恢复。')
        if self._instance_id:
            lines.insert(0, '只读实例：'+self._instance_id)
        return '\n'.join(lines)
