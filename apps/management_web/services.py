"""R1 adapters: synthetic read-only data and explicitly unavailable AI/video services."""

from datetime import datetime, timedelta, timezone

from .contracts import MetricObservation, MonitoringSnapshot


DEVICES = ({"id": "demo-a", "name": "演示池 A"}, {"id": "demo-b", "name": "演示池 B"})
VIEWS = ("available", "stale", "partial", "invalid", "missing")


class DemoMonitoring:
    def __init__(self):
        self.observed = datetime.now(timezone.utc) - timedelta(minutes=3)

    def devices(self):
        return [dict(device) for device in DEVICES]

    def snapshot(self, device_id, view="available"):
        if device_id not in {d["id"] for d in DEVICES} or view not in VIEWS:
            raise ValueError("INVALID_MONITORING_SELECTION")
        now = datetime.now(timezone.utc)
        observed = self.observed - (timedelta(hours=2) if view == "stale" else timedelta())
        quality = {"missing": "missing", "partial": "partial", "invalid": "invalid"}.get(view, "valid")
        freshness = "unknown" if view == "missing" else "stale" if (now-observed).total_seconds() > 600 else "fresh"
        values = (26.4, 7.5, 6.4) if device_id == "demo-a" else (27.1, 7.3, 5.8)
        metrics = []
        for index, (key, label, unit) in enumerate((("temperature_c", "水温", "°C"),
                ("ph", "pH", ""), ("dissolved_oxygen_mg_l", "溶解氧", "mg/L"))):
            value = values[index] if view not in ("missing", "invalid") else None
            if view == "partial" and index == 2:
                value = None
            metrics.append(MetricObservation(key, label, value, unit,
                "invalid" if view == "invalid" else "missing" if value is None else "valid",
                "独立 Demo adapter", observed.isoformat() if view != "missing" else None, freshness))
        trend = tuple({"observed_at": (observed-timedelta(minutes=(11-i)*20)).isoformat(),
            "temperature_c": round(values[0]+offset*.15, 2), "ph": round(values[1]+offset*.02, 2),
            "dissolved_oxygen_mg_l": round(values[2]+offset*.1, 2)}
            for i, offset in enumerate((-1, -2, 0, 1, 2, 1, -1, 0, 2, 3, 1, 0))) if view not in ("missing", "invalid") else ()
        return MonitoringSnapshot(device_id, "独立 Demo adapter · 非传感器采样", "demo",
            observed.isoformat() if view != "missing" else None, now.isoformat(), quality, freshness,
            tuple(metrics), trend)


class UnavailableAI:
    def availability(self):
        return {"connected": False, "status": "not_connected", "models": [],
                "message": "R1 尚未接入 AssistantService；本页面不会发送模型请求。"}

    def send(self, request):
        raise NotImplementedError("AI_SERVICE_NOT_CONNECTED")


class DemoVideo:
    def cameras(self):
        return [{"id": "demo-camera-a", "name": "演示摄像头 A", "location": "演示池 A",
            "status": "not_connected", "source_kind": "demo", "stream_url": None,
            "detection_status": "not_connected", "detections": []},
            {"id": "demo-camera-b", "name": "演示摄像头 B", "location": "演示池 B",
            "status": "not_connected", "source_kind": "demo", "stream_url": None,
            "detection_status": "not_connected", "detections": []}]


class DemoFiles:
    def files(self):
        return [{"id": "demo-file-1", "name": "鳗鲡养殖参考资料（演示条目）", "category": "养殖资料",
            "format": "PDF", "source": "Demo 元数据 · 非真实上传文件", "source_kind": "demo",
            "index_status": "not_indexed", "size": None, "download_url": None,
            "description": "仅用于验证文件列表与详情布局。没有保存文件，也未建立 AI 检索索引。"},
            {"id": "demo-file-2", "name": "设备操作说明（演示条目）", "category": "设备说明",
            "format": "DOCX", "source": "Demo 元数据 · 非真实上传文件", "source_kind": "demo",
            "index_status": "not_indexed", "size": None, "download_url": None,
            "description": "未来文件管理、索引任务与知识检索将使用独立接口。"}]


class DemoEvents:
    def __init__(self):
        self.started = datetime.now(timezone.utc)

    def events(self):
        definitions = (("DEMO-001", "演示池 A", "水质", "warning", "pending", "低氧提示样例", "用于验证告警详情，并非当前水质诊断。"),
            ("DEMO-002", "演示摄像头 A", "设备", "info", "pending", "设备未接入样例", "当前没有视频流或 NPU 检测结果。"),
            ("DEMO-003", "演示池 B", "系统", "info", "closed", "演示记录样例", "已处理仅为样例字段，不代表已实现处理工作流。"))
        return [{"id": key, "device": device, "type": kind, "severity": severity, "status": status,
            "title": title, "description": description, "source_kind": "demo",
            "occurred_at": (self.started-timedelta(minutes=(i+1)*18)).isoformat(),
            "attachments": []} for i, (key, device, kind, severity, status, title, description) in enumerate(definitions)]
