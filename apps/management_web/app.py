"""Independent presentation API and explicitly enabled local device ingestion."""

from dataclasses import asdict
from hmac import compare_digest
from ipaddress import ip_address

from flask import Flask, jsonify, request

from .services import DemoEvents, DemoFiles, DemoMonitoring, DemoVideo, UnavailableAI
from apps.monitoring.contracts import IngestionError, strict_json, valid_token


def create_app(*, monitoring=None, ai=None, video=None, files=None, events=None,
               allowed_hosts=("127.0.0.1:8766", "localhost:8766", "localhost"),
               data_service=None, ingestion_token=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024
    if ingestion_token is not None and (data_service is None or not valid_token(ingestion_token)):
        raise ValueError("INVALID_INGESTION_CONFIG")
    if data_service is not None:
        monitoring, video, events = data_service, data_service, data_service
    monitoring = monitoring if monitoring is not None else DemoMonitoring()
    ai = ai if ai is not None else UnavailableAI()
    video = video if video is not None else DemoVideo()
    files = files if files is not None else DemoFiles()
    events = events if events is not None else DemoEvents()
    hosts = frozenset(allowed_hosts)

    @app.before_request
    def local_boundary():
        if request.host.lower() not in hosts:
            return jsonify(error_code="HOST_REJECTED"), 403
        origin = request.headers.get("Origin")
        if origin and origin != f"{request.scheme}://{request.host}":
            return jsonify(error_code="ORIGIN_REJECTED"), 403
        if request.content_length is not None and request.content_length > app.config["MAX_CONTENT_LENGTH"]:
            return jsonify(error_code="REQUEST_TOO_LARGE"), 413

    @app.after_request
    def response_headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/bootstrap")
    def bootstrap():
        devices = monitoring.devices()
        selected = request.args.get("device") or (devices[0]["id"] if devices else None)
        snapshot = asdict(monitoring.snapshot(selected)) if selected else None
        mode = getattr(monitoring, "data_mode", "demo")
        connection = (snapshot.get("connectivity", "never_received") if snapshot else "never_received") if mode != "demo" else "demo"
        return jsonify(schema_version=1, application="management-web-r1", data_mode=mode,
            devices=devices, monitoring=snapshot, cameras=video.cameras(),
            events=events.events(), files=files.files(), ai=ai.availability(),
            connections=[{"name": "监测数据", "status": connection, "description": "模拟器 HTTP 上报" if mode == "simulator" else "独立演示适配器"},
                {"name": "传感器 / 数据库", "status": "not_connected", "description": "尚未接入"},
                {"name": "视频 / NPU", "status": "not_connected", "description": "尚未接入"},
                {"name": "AI Runtime", "status": "not_connected", "description": "保留现有 Runtime，待桥接"}])

    @app.post("/api/ingestion/batches")
    def ingest_batch():
        if ingestion_token is None:
            return jsonify(error_code="INGESTION_DISABLED"), 403
        try:
            local = ip_address(request.remote_addr or "").is_loopback
        except ValueError:
            local = False
        supplied = request.headers.get("X-Simulator-Token", "")
        if not local or not valid_token(supplied) or not compare_digest(supplied, ingestion_token):
            return jsonify(error_code="INGESTION_ACCESS_DENIED"), 403
        # Browser-origin writes are not a device transport. No forwarded IP trust or CORS.
        if request.headers.get("Origin") or request.mimetype != "application/json":
            return jsonify(error_code="INGESTION_TRANSPORT_REJECTED"), 403
        value = strict_json(request.get_data(cache=False))
        return jsonify(data_service.ingest(value))

    @app.get("/api/monitoring")
    def readings():
        devices = monitoring.devices()
        device = request.args.get("device") or (devices[0]["id"] if devices else None)
        if device is None:
            return jsonify(error_code="NO_MONITORING_DEVICE"), 404
        return jsonify(asdict(monitoring.snapshot(device, request.args.get("view", "available"))))

    @app.get("/api/monitoring/history")
    def monitoring_history():
        if data_service is None:
            return jsonify(error_code="HISTORY_SERVICE_NOT_CONNECTED"), 503
        devices = data_service.devices()
        device = request.args.get("device") or (devices[0]["id"] if devices else None)
        raw_limit = request.args.get("limit")
        limit = int(raw_limit) if raw_limit is not None else None
        return jsonify(items=data_service.history(device, request.args.get("channel", "water"), limit))

    def collection(items):
        query = request.args.get("q", "").strip()
        if len(query) > 128:
            raise ValueError("INVALID_FILTER")
        category = request.args.get("category", "")
        severity = request.args.get("severity", "")
        status = request.args.get("status", "")
        return [item for item in items if (not query or query.casefold() in
            " ".join(str(item.get(key, "")) for key in ("name", "title", "device", "category")).casefold())
            and (not category or item.get("category") == category)
            and (not severity or item.get("severity") == severity)
            and (not status or item.get("status") == status)]

    @app.get("/api/events")
    def event_list():
        return jsonify(items=collection(events.events()), source_kind=getattr(monitoring, "data_mode", "demo"))

    @app.get("/api/files")
    def file_list():
        return jsonify(items=collection(files.files()), source_kind="demo")

    def detail(items, identifier):
        item = next((item for item in items if item["id"] == identifier), None)
        return jsonify(item) if item else (jsonify(error_code="NOT_FOUND"), 404)

    @app.get("/api/events/<identifier>")
    def event_detail(identifier):
        return detail(events.events(), identifier)

    @app.get("/api/files/<identifier>")
    def file_detail(identifier):
        return detail(files.files(), identifier)

    @app.get("/api/ai/status")
    def ai_status():
        return jsonify(ai.availability())

    @app.post("/api/ai/messages")
    def disabled_ai():
        # Intentionally never invokes injected services before a secured integration stage.
        return jsonify(error_code="AI_SERVICE_NOT_CONNECTED"), 503

    @app.errorhandler(ValueError)
    def invalid_input(_error):
        return jsonify(error_code="INVALID_SELECTION"), 400

    @app.errorhandler(IngestionError)
    def ingestion_error(error):
        return jsonify(error_code=error.code), error.http_status

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error_code="REQUEST_TOO_LARGE"), 413

    @app.errorhandler(500)
    def internal_error(_error):
        return jsonify(error_code="SERVICE_UNAVAILABLE"), 500

    return app
