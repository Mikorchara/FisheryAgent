import argparse
import os
from pathlib import Path

from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="Fishery management Web (local monitoring, no model requests)")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--enable-ingestion", action="store_true", help="Local simulator writes, token required")
    parser.add_argument("--legacy-demo", action="store_true", help="Isolated R1 static Demo; no ingestion")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.legacy_demo and args.enable_ingestion:
        parser.error("LEGACY_DEMO_CANNOT_INGEST")
    data_service, token = None, None
    if not args.legacy_demo:
        from apps.monitoring.repository import MonitoringRepository
        from apps.monitoring.service import MonitoringService
        from apps.monitoring.contracts import valid_token
        if args.enable_ingestion:
            token = os.environ.get("FISHERY_SIM_INGEST_TOKEN", "")
            if not valid_token(token):
                parser.error("INGESTION_TOKEN_REQUIRED: set a 32-128 character alphanumeric development token")
        path = Path(__file__).resolve().parents[2]/"outputs"/"management_web"/"monitoring.sqlite3"
        data_service = MonitoringService(MonitoringRepository(path))
    app = create_app(allowed_hosts=(f"127.0.0.1:{args.port}", f"localhost:{args.port}"),
                     data_service=data_service, ingestion_token=token)
    print(f"Management Web · Local: http://127.0.0.1:{args.port}", flush=True)
    app.run(host="127.0.0.1", port=args.port, debug=False, load_dotenv=False)


if __name__ == "__main__":
    main()
