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
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--evt2', action='store_true', help='Include grade transitions and resolved maintenance fixtures')
    parser.add_argument('--ack-cycles', action='store_true', help='ACK one ended and one active fictional cycle; implies --evt2')
    parser.add_argument('--manual-end', action='store_true', help='Freeze fictional observations 95 seconds after reports stop')
    args = parser.parse_args()
    args.evt2 = args.evt2 or args.ack_cycles
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
            if args.evt2:
                oxygen = {10:4.2, 11:2.2, 12:4.1, 20:4.2, 21:2.2, 57:4.2, 58:2.2, 59:2.2}.get(index, 6.4)
                batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=oxygen, min=oxygen, max=oxygen, latest=oxygen)
                if index == 40:
                    batch['visual']['anomaly_counts']['suspected_dead'] = 1
            service.ingest(batch)
            if args.ack_cycles and index in (21, 58):
                event = next(e for e in service.events() if e['code']=='OXYGEN_CRITICAL_LOW' and e['lifecycle_state']=='ACTIVE')
                h=event['handling']
                service.acknowledge_event(dict(event_id=event['id'],cycle_id=h['cycle_id'],
                    grade_token=h['grade_token'],grade_version=h['grade_version'],revision=h['revision'],request_id=str(uuid.uuid4())))
        if args.manual_end:
            now += timedelta(seconds=95)
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
