"""Explicit independent device HTTP receiver. Never starts the management Web/AI."""
import argparse
from datetime import datetime,timezone
from hmac import compare_digest
from ipaddress import ip_address
import json
import logging
import os
from pathlib import Path
from time import monotonic
from threading import Lock
from flask import Flask,jsonify,request
from apps.monitoring.contracts import identifier,valid_token
from .contracts import MAX_BYTES,ReportError
from .storage import ReportStore,safe_directory


def create_receiver(store,*,device_id,token,clock=lambda:datetime.now(timezone.utc)):
    identifier(device_id)
    if not valid_token(token):raise ReportError('DEVICE_REPORT_TOKEN_REQUIRED')
    app=Flask(__name__,static_folder=None);app.config['MAX_CONTENT_LENGTH']=MAX_BYTES
    rate_lock=Lock();last=[]

    @app.before_request
    def boundary():
        if request.path!='/api/fish/reports' or request.method!='POST':
            return jsonify(error_code='DEVICE_REPORT_ENDPOINT_ONLY'),404
        supplied=request.headers.get('X-Device-Token','')
        if request.headers.get('Origin') or not valid_token(supplied) or not compare_digest(supplied,token):
            return jsonify(error_code='DEVICE_REPORT_ACCESS_DENIED'),403
        if request.mimetype!='application/json':return jsonify(error_code='DEVICE_REPORT_JSON_REQUIRED'),400
        # Bounded rolling admission, no remote identifier or content in diagnostics.
        with rate_lock:
            now=monotonic();last[:]=[t for t in last if t>now-60]
            if len(last)>=60:return jsonify(error_code='DEVICE_REPORT_RATE_LIMITED'),429
            last.append(now)

    @app.errorhandler(413)
    def too_large(_):return jsonify(error_code='DEVICE_REPORT_TOO_LARGE'),413

    @app.post('/api/fish/reports')
    def receive():
        try:return jsonify(store.receive(request.get_data(cache=False),device_id=device_id,now=clock()))
        except ReportError as error:return jsonify(error_code=error.code),error.status

    @app.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    return app


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--device-id',required=True)
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--init-store',action='store_true');actions.add_argument('--check',action='store_true');actions.add_argument('--serve',action='store_true')
    parser.add_argument('--bind',default='127.0.0.1');parser.add_argument('--port',type=int,default=8780)
    args=parser.parse_args(argv)
    try:
        identifier(args.device_id);safe_directory(args.directory)
        host=ip_address(args.bind)
        if host.version!=4 or not (host.is_loopback or host.is_private) or host.is_unspecified or host.is_multicast or host.is_reserved:
            raise ReportError('DEVICE_REPORT_BIND_REJECTED')
        if not 1<=args.port<=65535:raise ReportError('DEVICE_REPORT_PORT_INVALID')
        if args.check:
            print(json.dumps(dict(code='DEVICE_REPORT_CONFIG_CHECKED',store_exists=(args.directory/'device-reports.sqlite3').is_file(),
                database_opened=False,credential_checked=False,network_requests=0)));return 0
        if args.init_store:
            ReportStore.initialize(args.directory);print(json.dumps(dict(code='DEVICE_REPORT_STORE_CREATED')));return 0
        token=os.environ.get('FISHERY_DEVICE_REPORT_TOKEN','')
        if not valid_token(token):raise ReportError('DEVICE_REPORT_TOKEN_REQUIRED')
        app=create_receiver(ReportStore(args.directory),device_id=args.device_id,token=token)
        # Suppress HTTP request lines: user-controlled URLs must not reach logs.
        logging.getLogger('werkzeug').setLevel(logging.CRITICAL)
        from werkzeug.serving import make_server
        server=make_server(str(host),args.port,app)
        print(json.dumps(dict(code='DEVICE_REPORT_LISTENING',port=args.port)),flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()
        return 0
    except (ReportError,ValueError,OSError) as error:
        print(json.dumps(dict(code=error.code if isinstance(error,ReportError) else 'DEVICE_REPORT_START_FAILED')));return 1


if __name__=='__main__':raise SystemExit(main())
