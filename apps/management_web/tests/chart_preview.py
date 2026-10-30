"""Manual chart UI preview: in-memory fictional data, no DB/credentials/Provider.

Run with this repository's Python: python -I -B <this-file> --port 8786.
The local server expires after ten minutes; POST /__chart_preview__/stop closes it.
This helper is never imported by the product entry point.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from apps.management_web.app import create_app
from apps.management_web.services import DemoMonitoring


class PreviewMonitoring(DemoMonitoring):
    def snapshot(self, device_id, view='available'):
        snapshot = super().snapshot(device_id, view)
        if view in ('missing', 'invalid'):
            return snapshot
        end = datetime.fromisoformat(snapshot.observed_at)
        trend = []
        for i in range(360):
            observed = end-timedelta(seconds=(359-i)*10)
            # Include real time gaps and session boundaries without changing data.
            if 125 <= i < 145:
                continue
            row = dict(observed_at=observed.isoformat(), received_at=(observed+timedelta(seconds=1)).isoformat(),
                window_start=(observed-timedelta(seconds=10)).isoformat(), window_duration_s=10,
                session_id='preview-a' if i < 145 else 'preview-b', batch_id='preview-'+str(i),
                temperature_c=round(25+math.sin(i/28)*.8+i*.002, 3), ph=round(7.4+math.cos(i/35)*.12, 3),
                dissolved_oxygen_mg_l=round(6.2+math.sin(i/18)*.5, 3))
            if 210 <= i < 214:
                row['ph'] = None
            trend.append(row)
        metrics=tuple(replace(metric,value=trend[-1][metric.id] if metric.quality=='valid' else None)
                      for metric in snapshot.metrics)
        return replace(snapshot, trend=tuple(trend), metrics=metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8786)
    parser.add_argument('--demo-video',type=Path,help='Explicit local MP4 preview, independent of fictional observations')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('INVALID_PORT')
    from werkzeug.serving import make_server
    from apps.management_web.demo_video import LocalDemoVideo
    app = create_app(monitoring=PreviewMonitoring(), allowed_hosts=(f'127.0.0.1:{args.port}',),
                     demo_video=LocalDemoVideo.open(args.demo_video) if args.demo_video else None)
    stopped = False

    @app.post('/__chart_preview__/stop')
    def stop():
        nonlocal stopped
        stopped = True
        return {'status':'stopping'}

    server = make_server('127.0.0.1', args.port, app)
    server.timeout = .5
    deadline = time.monotonic()+600
    print(f'FICTIONAL_CHART_PREVIEW http://127.0.0.1:{args.port} · no database or model calls', flush=True)
    try:
        while not stopped and time.monotonic() < deadline:
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
