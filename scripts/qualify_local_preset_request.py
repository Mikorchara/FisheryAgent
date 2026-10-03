"""One explicitly selected local request, never a batch scan or publisher."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import time

from fishery_ai.capability_store import CapabilityStore
from fishery_ai.credential_paths import private_project_location
from fishery_ai.credentials import CredentialStore
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.contracts import Mode, Usage
from fishery_ai.manual import ManualRequest
from fishery_ai.model_gateway import GatewayError, ModelMessage, ModelRequest, ProfileRegistry
from fishery_ai.model_options import GenerationOptions, ReasoningMode, ReasoningOptions, Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter

IDENTITY = ('ollama', 'generic_openai_chat', 'http://127.0.0.1:11434/v1', 'qwen3.5:4b')


class InspectionGateway(OpenAICompatibleAdapter):
    """Capture safe finish metadata; never retain raw model text."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.finish_reason = self.returned_model = None
        self.reasoning_present = False

    def _response(self, response):
        self.returned_model = response.model
        self.finish_reason = response.choices[0].finish_reason
        message = response.choices[0].message
        self.reasoning_present = bool(getattr(message, 'reasoning_content', None)
                                      or getattr(message, 'reasoning', None))
        return super()._response(response)

    def _event(self, chunk):
        self.returned_model = chunk.model or self.returned_model
        for choice in chunk.choices:
            self.finish_reason = choice.finish_reason or self.finish_reason
            self.reasoning_present |= bool(getattr(choice.delta, 'reasoning_content', None)
                                           or getattr(choice.delta, 'reasoning', None))
        return super()._event(chunk)


def qualify(gateway, runtime, mode, streaming, *, manual=False):
    if (runtime.service_id, runtime.adapter_id, runtime.base_url, runtime.model) != IDENTITY:
        raise GatewayError('QUALIFICATION_IDENTITY_MISMATCH')
    if runtime.auth_spec.value != 'NONE' or mode not in (ReasoningMode.ON, ReasoningMode.OFF):
        raise GatewayError('QUALIFICATION_OPTION_INVALID')
    # Diagnostic-only UNKNOWN bypass for this explicitly chosen mode. A token
    # limit is a request budget, not persistent capability evidence.
    caps = replace(runtime.capabilities, max_output_tokens=Support.SUPPORTED,
        reasoning_on=Support.SUPPORTED if mode == ReasoningMode.ON else runtime.capabilities.reasoning_on,
        reasoning_off=Support.SUPPORTED if mode == ReasoningMode.OFF else runtime.capabilities.reasoning_off,
        streaming=Support.SUPPORTED if streaming else runtime.capabilities.streaming,
        thinking_streaming_combination=Support.SUPPORTED if streaming and mode == ReasoningMode.ON
            else runtime.capabilities.thinking_streaming_combination,
        thinking_off_streaming_combination=Support.SUPPORTED if streaming and mode == ReasoningMode.OFF
            else runtime.capabilities.thinking_off_streaming_combination)
    runtime = replace(runtime, capabilities=caps, max_retries=0,
        default_generation=GenerationOptions(), default_reasoning=ReasoningOptions(),
        read_timeout_s=30, total_timeout_s=60)
    result = dict(thinking=mode.value, streaming=streaming, manual_v1=manual,
        status='failure', retry=0, max_output_tokens=64, delta_count=0, reasoning_delta_count=0,
        ttft_ms=None, content_ttft_ms=None, usage=asdict(Usage()))
    start = time.monotonic()
    try:
        if manual:
            if streaming: raise GatewayError('QUALIFICATION_OPTION_INVALID')
            body = {'model':runtime.model, 'messages':[{'role':'user','content':'只回复 OK'}],
                    'max_tokens':64, 'reasoning_effort':'none' if mode == ReasoningMode.OFF else 'high'}
            response = gateway.manual_complete(ManualRequest.from_dict(body, model=runtime.model), runtime)
            choice = response.raw.get('choices', [{}])[0]
            message = choice.get('message', {})
            has_content = bool(message.get('content'))
            result['usage'] = asdict(response.usage)
            gateway.finish_reason = choice.get('finish_reason')
            gateway.returned_model = response.raw.get('model')
            gateway.reasoning_present = bool(message.get('reasoning_content') or message.get('reasoning'))
        else:
            request = ModelRequest(Mode.CHAT, (ModelMessage('user', '只回复 OK'),),
                generation=GenerationOptions(max_output_tokens=64), reasoning=ReasoningOptions(mode))
            if streaming:
                events = gateway.stream(request, runtime)
                try:
                    for event in events:
                        if event.delta or event.reasoning_delta:
                            elapsed = round((time.monotonic()-start)*1000, 3)
                            if result['ttft_ms'] is None: result['ttft_ms'] = elapsed
                        if event.delta:
                            result['delta_count'] += 1
                            if result['content_ttft_ms'] is None: result['content_ttft_ms'] = elapsed
                        if event.reasoning_delta: result['reasoning_delta_count'] += 1
                        if event.usage is not None: result['usage'] = asdict(event.usage)
                finally: events.close()
                has_content = result['delta_count'] > 0
            else:
                response = gateway.complete(request, runtime)
                has_content = bool(response.text.strip())
                result['usage'] = asdict(response.usage)
        result.update(content_present=has_content, finish_reason=gateway.finish_reason,
            returned_model=runtime.model if gateway.returned_model == runtime.model else None,
            reasoning_present=gateway.reasoning_present)
        if not has_content: result['error_code'] = 'PROBE_NO_CONTENT'
        elif gateway.finish_reason != 'stop': result['error_code'] = 'QUALIFICATION_NOT_COMPLETED'
        elif gateway.returned_model != runtime.model: result['error_code'] = 'MODEL_IDENTITY_MISMATCH'
        elif mode == ReasoningMode.OFF and (gateway.reasoning_present
                or result['usage'].get('reasoning_tokens') not in (None, 0)):
            result['error_code'] = 'UNEXPECTED_REASONING'
        else: result['status'] = 'success'
    except GatewayError as exc: result['error_code'] = exc.code
    except Exception: result['error_code'] = 'QUALIFICATION_FAILED'
    result.update(latency_ms=round((time.monotonic()-start)*1000,3), attempts=gateway.request_attempts)
    return result


def main():
    parser = argparse.ArgumentParser(description='仅一次明确模式的 Ollama 资格验证，无自动发布')
    parser.add_argument('--confirm-network', action='store_true')
    parser.add_argument('--profile-id', required=True)
    parser.add_argument('--thinking', choices=('on','off'), required=True)
    parser.add_argument('--streaming', action='store_true')
    parser.add_argument('--manual-v1', action='store_true')
    args = parser.parse_args()
    if not args.confirm_network:
        print('NETWORK_CONFIRMATION_REQUIRED')
        return 2
    root = Path.cwd()
    if not (root/'pyproject.toml').is_file():
        print('WORKSPACE_REQUIRED')
        return 2
    store = CustomProfileStore(root/'outputs/custom_profiles')
    profile = next((p for p in store.load() if p.profile_id == args.profile_id), None)
    if profile is None:
        print('SAVED_CONNECTION_REQUIRED')
        return 2
    if ((profile.service_id, profile.adapter_id, profile.base_url, profile.model) != IDENTITY
            or profile.auth_spec.value != 'NONE'):
        print('QUALIFICATION_IDENTITY_MISMATCH')
        return 2
    location = private_project_location(root)
    credentials = CredentialStore(location.env_path, private_location=location)
    resolved = CapabilityStore(root/'outputs/capability-evidence').apply(profile)
    runtime = ProfileRegistry([resolved], credentials).snapshot(profile.profile_id, apply_runtime_defaults=False)
    outcome = qualify(InspectionGateway(), runtime, ReasoningMode(args.thinking), args.streaming,
                      manual=args.manual_v1)
    report = dict(identity=list(IDENTITY), profile_id=profile.profile_id,
                  validated_at=datetime.now(timezone.utc).isoformat(), result=outcome)
    destination = root/'outputs/preset-qualification'
    destination.mkdir(parents=True, exist_ok=True)
    filename = datetime.now(timezone.utc).strftime('ollama-%Y%m%dT%H%M%S%f.json')
    (destination/filename).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    # Evidence writes are a separate reviewed step, not an automatic side effect.
    print(json.dumps(report, ensure_ascii=True))
    return 0 if outcome['status']=='success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
