"""Loopback end-to-end device transport; no external sockets, AI or NPU."""

from datetime import datetime, timezone
from pathlib import Path
import socket
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from werkzeug.serving import make_server, WSGIRequestHandler
from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from apps.simulator.transport import HttpReporter, ReportError
from apps.simulator.__main__ import run


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):pass


class LocalHttpTests(unittest.TestCase):
    def test_real_http_periodic_reports_restart_and_page_data(self):
        original = socket.socket.connect
        def local_only(sock,address):
            if address[0] not in ('127.0.0.1','::1'):
                raise AssertionError('external network disabled')
            return original(sock,address)
        with tempfile.TemporaryDirectory() as temp, patch.object(socket.socket,'connect',local_only):
            repository=MonitoringRepository(Path(temp)/'local.sqlite3')
            service=MonitoringService(repository)
            token='t'*64
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1',0))
                port=reserve.getsockname()[1]
            app=create_app(data_service=service,ingestion_token=token,allowed_hosts=(f'127.0.0.1:{port}',))
            safe_errors=[]
            @app.after_request
            def capture_safe_error(response):
                if response.status_code >= 400 and response.is_json:
                    safe_errors.append((response.get_json() or {}).get('error_code','UNKNOWN_SAFE_ERROR'))
                return response
            server=make_server('127.0.0.1',port,app,request_handler=QuietHandler)
            thread=Thread(target=server.serve_forever,daemon=True)
            thread.start()
            url=f'http://127.0.0.1:{port}'
            try:
                reporter=HttpReporter(url,token)
                try:
                    run(Simulator(start=datetime.now(timezone.utc)),reporter,interval_s=1,windows=3,emit=lambda _:None)
                except ReportError:
                    self.fail('Loopback ingestion failed: '+','.join(safe_errors))
                self.assertEqual(len(repository.history('sim-pond-1','water')),3)
                run(Simulator(start=datetime.now(timezone.utc)),HttpReporter(url,token),interval_s=1,windows=1,emit=lambda _:None)
                self.assertEqual(len(repository.history('sim-pond-1','water')),4)
                import json
                with urlopen(url+'/api/bootstrap',timeout=2) as response:
                    bootstrap=json.load(response)
                self.assertEqual(bootstrap['data_mode'],'simulator')
                self.assertEqual(bootstrap['monitoring']['connectivity'],'online')
                self.assertEqual(bootstrap['monitoring']['batch_id'],bootstrap['cameras'][0]['batch_id'])
                with urlopen(url+'/',timeout=2) as response:
                    self.assertIn('source-notice',response.read().decode())
                reporter=HttpReporter(url,'x'*64)
                # Generate one past window; access is rejected before any batch evaluation.
                with self.assertRaisesRegex(ReportError,'REPORT_HTTP_403'):
                    reporter.send(Simulator(start=datetime.now(timezone.utc)).advance())
                reporter.close()
            finally:
                server.shutdown()
                thread.join(timeout=3)
                server.server_close()
                self.assertFalse(thread.is_alive())


if __name__=='__main__':unittest.main()
