"""Local content management. No LLM writes, arbitrary paths or retrieval settings."""
from hmac import compare_digest
from ipaddress import ip_address
import json
import secrets

from flask import jsonify, request, Response
from apps.knowledge.repository import KnowledgeError


def register_knowledge_api(app, service):
    token=secrets.token_urlsafe(32)

    @app.errorhandler(KnowledgeError)
    def knowledge_error(error):
        status=409 if error.code=='KNOWLEDGE_CONFLICT' else 404 if error.code=='KNOWLEDGE_NOT_FOUND' else 503 if error.code=='KNOWLEDGE_STORAGE_ERROR' else 400
        return jsonify(error_code=error.code),status

    def gate(*, write=False):
        try: local=ip_address(request.remote_addr or '').is_loopback
        except ValueError: local=False
        if not local:return jsonify(error_code='KNOWLEDGE_LOCAL_ONLY'),403
        if service is None:return jsonify(error_code='KNOWLEDGE_NOT_CONNECTED'),503
        if write:
            supplied=request.headers.get('X-Management-Knowledge','')
            if not supplied.isascii() or not compare_digest(token,supplied):
                return jsonify(error_code='KNOWLEDGE_ACCESS_DENIED'),403
            if request.mimetype!='application/json':
                return jsonify(error_code='INVALID_KNOWLEDGE_CONTENT'),400

    def body():
        def pairs(items):
            value={}
            for key,item in items:
                if key in value:raise ValueError()
                value[key]=item
            return value
        try:
            return json.loads(request.get_data(),object_pairs_hook=pairs,
                              parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        except (ValueError,UnicodeError,RecursionError):
            raise KnowledgeError('INVALID_KNOWLEDGE_CONTENT') from None

    @app.get('/api/knowledge')
    def knowledge_list():
        failure=gate()
        if failure is not None:return failure
        try: offset=int(request.args.get('offset','0'))
        except ValueError:raise KnowledgeError('INVALID_KNOWLEDGE_FILTER') from None
        return jsonify(**service.list(query=request.args.get('q',''),category=request.args.get('category',''),
            status=request.args.get('status',''),offset=offset),write_token=token)

    @app.get('/api/knowledge/<key>')
    def knowledge_detail(key):
        failure=gate()
        return failure if failure is not None else jsonify(service.get(key))

    @app.get('/api/knowledge/export')
    def knowledge_export():
        failure=gate()
        if failure is not None:return failure
        if set(request.args)-{'format','status'} or any(len(request.args.getlist(k))!=1 for k in request.args):
            raise KnowledgeError('INVALID_KNOWLEDGE_EXPORT')
        payload,mime,filename=service.export(format=request.args.get('format','json'),status=request.args.get('status','active'))
        return Response(payload,content_type=mime+'; charset=utf-8',headers={
            'Content-Disposition':f'attachment; filename="{filename}"','X-Content-Type-Options':'nosniff'})

    @app.post('/api/knowledge')
    def knowledge_create():
        failure=gate(write=True)
        return failure if failure is not None else (jsonify(service.create(body())),201)

    @app.patch('/api/knowledge/<key>')
    def knowledge_edit(key):
        failure=gate(write=True)
        return failure if failure is not None else jsonify(service.edit(key,body()))

    @app.post('/api/knowledge/<key>/status')
    def knowledge_status(key):
        failure=gate(write=True)
        return failure if failure is not None else jsonify(service.set_status(key,body()))

    @app.post('/api/knowledge/search')
    def knowledge_search():
        failure=gate(write=True)
        if failure is not None:return failure
        from apps.ai_service.business_tools.fishery_knowledge import validate_arguments, search_fishery_knowledge
        try: arguments=validate_arguments(body())
        except ValueError:raise KnowledgeError('INVALID_KNOWLEDGE_QUERY') from None
        return jsonify(search_fishery_knowledge(arguments,service=service))
