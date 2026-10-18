"""Settings HTTP boundary shares the Assistant's local browser authorization."""
from flask import jsonify, request
from apps.ai_service.settings import SettingsError
from apps.ai_backend.project_env import EnvWriteError


def register_settings_api(app, service, assistant, gate):
    def response(value):
        return jsonify(**value, browser_token=assistant.browser_token)

    def checked():
        failure = gate(write=request.method=='POST')
        if failure is not None:
            return failure
        if service is None:
            return jsonify(error_code='SETTINGS_NOT_CONNECTED'),503

    @app.get('/api/settings')
    @app.post('/api/settings')
    def preferences():
        failure = checked()
        if failure is not None:
            return failure
        return response(service.public() if request.method=='GET' else service.save(request.get_json(silent=True)))

    @app.post('/api/settings/credentials')
    def credential():
        failure = checked()
        if failure is not None:
            return failure
        return jsonify(credential=service.change_credential(request.get_json(silent=True)))

    @app.post('/api/settings/credentials/test')
    def credential_test():
        failure=checked()
        if failure is not None:return failure
        return jsonify(test=service.connection_tests.run(request.get_json(silent=True)))

    @app.post('/api/settings/budgets')
    def output_budget():
        failure=checked()
        if failure is not None:return failure
        return response(service.save_budget(request.get_json(silent=True)))

    @app.errorhandler(SettingsError)
    @app.errorhandler(EnvWriteError)
    def settings_error(error):
        # Never serialize exception repr, submitted fields, private paths or file bytes.
        return jsonify(error_code=error.code),409
