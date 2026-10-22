"""Bounded EVT-1 visual preview using fictional data and a disposable SQLite instance.

python -I -B apps/management_web/tests/event_preview.py --port 8787
No user paths, credentials, AI service or HTTP ingestion are enabled.
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    from werkzeug.serving import make_server
    now = datetime.now(timezone.utc)
    start = now - timedelta(seconds=600)
    with tempfile.TemporaryDirectory(prefix='fishery-evt1-preview-') as temporary:
        repo = MonitoringRepository(Path(temporary) / 'monitoring.sqlite3')
        service = MonitoringService(repo, clock=lambda: now)
        sim = Simulator(start=start, seed=42, session_id='evt1-fictional-preview')
        for index in range(60):
            batch = sim.advance(10)
            now = datetime.fromisoformat(batch['timestamp'])
            batch['visual']['anomaly_counts'] = dict(suspected_lesion=0, surface_anomaly=0, suspected_dead=0)
            if index >= 57:
                batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2, min=2.2, max=2.2, latest=2.2)
                batch['water']['metrics']['ph'].update(mean=4, min=4, max=4, latest=4)
                batch['visual']['anomaly_counts'].update(suspected_lesion=2 if index < 59 else 0, surface_anomaly=1)
            if index == 59:
                batch['water']['metrics']['ph'].update(mean=None, min=None, max=None, latest=None, valid_samples=0)
            service.ingest(batch)
        app = create_app(data_service=service, allowed_hosts=(f'127.0.0.1:{args.port}',))
        stopped = False

        @app.post('/__evt1_preview__/stop')
        def stop():
            nonlocal stopped
            stopped = True
            return {'status': 'stopping'}

        server = make_server('127.0.0.1', args.port, app)
        server.timeout = .5
        deadline = time.monotonic() + 600
        print(f'EVT1_FICTIONAL_PREVIEW http://127.0.0.1:{args.port} · disposable DB; no Provider', flush=True)
        try:
            while not stopped and time.monotonic() < deadline:
                server.handle_request()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
