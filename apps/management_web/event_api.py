"""Local event maintenance capability; never available to the model or remote writers."""

from hmac import compare_digest
from ipaddress import ip_address
import secrets

from flask import jsonify, request

from apps.monitoring.contracts import strict_json
from apps.monitoring.event_records import EventRecordError


def register_event_api(app, service):
    token = secrets.token_urlsafe(32)

    def local():
        try:
            return ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            return False

    def access():
        enabled = service is not None and local()
        return dict(enabled=enabled, write_token=token if enabled else None)

    @app.errorhandler(EventRecordError)
    def error(exc):
        return jsonify(error_code=exc.code), exc.status

    def gate():
        if service is None:
            raise EventRecordError('EVENT_MAINTENANCE_UNAVAILABLE', 503)
        supplied = request.headers.get('X-Management-Events', '')
        if not local() or not supplied.isascii() or not compare_digest(token, supplied):
            raise EventRecordError('EVENT_ACCESS_DENIED', 403)
        if request.mimetype != 'application/json':
            raise EventRecordError('INVALID_EVENT_DELETE')

    def body(commit=False):
        gate()
        value = strict_json(request.get_data())
        allowed = {'scope', 'event_id', 'revision'} if commit else {'scope', 'event_id'}
        required = {'scope', 'revision'} if commit else {'scope'}
        if not isinstance(value, dict) or set(value) - allowed or not required <= value.keys():
            raise EventRecordError('INVALID_EVENT_DELETE')
        return value

    @app.post('/api/events/deletion-preview')
    def preview():
        value = body()
        return jsonify(service.repository.prepare_event_deletion(value['scope'], value.get('event_id')))

    @app.post('/api/events/delete')
    def delete():
        value = body(commit=True)
        return jsonify(service.repository.delete_events(value['scope'], value.get('event_id'), value['revision']))

    return access
