"""Request-scoped POST SSE delivery; business execution stays in AI Service."""
import threading
from flask import Response, stream_with_context
from apps.ai_backend.assistant_events import AssistantEventChannel
from apps.ai_backend.assistant_activity import safe_code
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.execution import TERMINAL


def stream_response(prepared,handle,execute,epoch):
    """The caller has already claimed the handle exactly once, before headers/I/O."""
    channel=AssistantEventChannel(handle,epoch)
    try:
        handle._event_channel=channel
        decision=prepared.execution
        channel.emit('start',{'transport':'streaming','max_model_requests':3,
            'max_output_tokens':decision.max_output_tokens,'release_status':decision.profile.release_status,
            'execution_revision':decision.profile.revision,'device_id':prepared.device_id})

        def worker():
            try:
                result=execute()  # Existing Assistant + Runtime own the only Tool loop and commit.
                kind='final' if result['successful_turn'] else 'cancelled' if result['error_code']=='USER_CANCELLED' else 'error'
                channel.emit(kind,{'result':result},terminal=True)
            except Exception as error:
                code=safe_code(getattr(error,'code',None)) or 'AI_SERVICE_UNAVAILABLE'
                # execute already finalizes ordinary failures. Cover failures outside it too.
                if handle.state not in TERMINAL:
                    handle.finish(code)
                code=handle.error_code or code
                channel.emit('cancelled' if code=='USER_CANCELLED' else 'error',
                    {'error_code':code},terminal=True)
            finally:
                handle._event_channel=None

        response=Response(stream_with_context(channel.events()),mimetype='text/event-stream')
        response.headers['Cache-Control']='no-store'
        response.headers['X-Accel-Buffering']='no'
        response.call_on_close(handle.cancel)  # Including close before first response iteration.
        threading.Thread(target=worker,name='management-assistant-turn',daemon=True).start()
        return response
    except Exception as error:
        handle._event_channel=None
        code=safe_code(getattr(error,'code',None)) or 'AI_SERVICE_UNAVAILABLE'
        if handle.state not in TERMINAL:
            handle.finish(code)
        raise GatewayError(handle.error_code or code) from None
