"""Explicit, bounded real smoke check; never imported or invoked by offline tests."""
from dataclasses import asdict, replace
from pathlib import Path
import argparse
import json
import threading
import time

from fishery_ai.credential_paths import private_project_location
from fishery_ai.credentials import CredentialFileError, CredentialStore
from fishery_ai.contracts import Mode
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.manual import ManualRequest
from fishery_ai.model_gateway import GatewayError, ModelMessage, ModelRequest, ProfileRegistry
from fishery_ai.model_options import CapabilitySource, GenerationOptions, ReasoningMode, ReasoningOptions, Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.presets import preset_profiles
from fishery_ai.web import _builtin_profiles


def run_validation():
    # Same frozen R2 composition as Web / validate-real / historical validators.
    location = private_project_location(Path.cwd())
    credentials = CredentialStore(location.env_path, private_location=location)
    profiles = {p.profile_id:p for p in (*preset_profiles(include_candidates=True), *_builtin_profiles())}
    records = []
    for name, profile_id, manual, cancel in (
        ("cloud_preset_off", "preset-qwen-plus-off", False, False),
        ("local_preset_off", "preset-ollama-qwen35-off", False, False),
        ("local_thinking_cancel", "ollama-qwen35-4b-local", False, True),
        ("local_manual_off", "ollama-qwen35-4b-local", True, False),
    ):
        profile = profiles[profile_id]
        try:
            runtime = ProfileRegistry([profile], credentials).snapshot(profile_id, apply_runtime_defaults=not manual)
        except CredentialFileError:
            records.append({"case":name,"profile_id":profile_id,"status":"blocked",
                            "error_code":"CREDENTIAL_FILE_ERROR","credential_status":"unavailable",
                            "sdk_attempts":0})
            continue
        runtime = replace(runtime, max_retries=0, connect_timeout_s=5,
                          read_timeout_s=15, total_timeout_s=30)
        if cancel:
            # Bound this one diagnostic using the reviewed Ollama max_tokens API field.
            # Do not update a managed Profile, Evidence Store or Preset contract.
            caps = replace(runtime.capabilities, max_output_tokens=Support.SUPPORTED,
                           max_tokens_field="max_tokens").with_evidence("max_output_tokens", CapabilitySource.OFFICIAL_DOCS)
            runtime = replace(runtime, capabilities=caps)
        record = {"case":name,"profile_id":profile_id,"credential_status":runtime.credential.status.availability}
        if runtime.credential.status.availability == "MISSING":
            records.append({**record,"status":"failed","error_code":"SECRET_MISSING","sdk_attempts":0})
            continue
        clients, sent_fields = [], []
        wanted = {"model":runtime.model,"messages":[{"role":"user","content":"只回复 OK"}],
                  "reasoning_effort":"none", "max_tokens":32}
        body_matches = []
        def client_factory(runtime, remaining):
            client = OpenAICompatibleAdapter._make_async_client(runtime, remaining)
            clients.append(client)
            async def inspect_body(request):
                # Inspect JSON field names / equality only; never headers or credential values.
                body = json.loads(request.content)
                sent_fields.append(sorted(body))
                if manual:
                    body_matches.append(body == wanted)
            client._client.event_hooks["request"].append(inspect_body)
            return client
        adapter = OpenAICompatibleAdapter(async_client_factory=client_factory)
        handle = RequestHandle()
        handle.start()
        started = time.monotonic()
        def execute():
            with request_scope(handle):
                try:
                    if manual:
                        response = adapter.manual_complete(ManualRequest.from_dict(wanted, model=runtime.model), runtime)
                        returned_model = response.raw.get("model")
                        text_ok = bool(response.raw.get("choices"))
                    else:
                        question = "逐步推导一道复杂整数分解题，最后回复 OK。" if cancel else "只回复 OK"
                        model_request = ModelRequest(Mode.CHAT, (ModelMessage("user",question),),
                            generation=GenerationOptions(max_output_tokens=256 if cancel else 32),
                            reasoning=ReasoningOptions(ReasoningMode.ON) if cancel else None)
                        response = adapter.complete(model_request, runtime)
                        returned_model, text_ok = response.returned_model, bool(response.text.strip())
                    handle.check()
                    record.update(status="success",returned_model=returned_model,
                                  nonempty_output=text_ok,usage=asdict(response.usage))
                    handle.finish()
                except GatewayError as exc:
                    record.update(status="cancelled" if exc.code == "USER_CANCELLED" else "failed", error_code=exc.code)
                    handle.finish(exc.code)
                except Exception:
                    record.update(status="failed",error_code="VALIDATION_ERROR")
                    handle.finish("VALIDATION_ERROR")
        worker = threading.Thread(target=execute, name="explicit-runtime-validation", daemon=True)
        worker.start()
        if cancel:
            deadline = time.monotonic() + 5
            while adapter.request_attempts == 0 and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            time.sleep(1)
            before = handle.public_info()["state"]
            cancel_at = time.monotonic()
            handle.cancel()
            record["state_before_stop"] = before
            worker.join(8)
            record["cancel_ack_ms"] = round((time.monotonic()-cancel_at)*1000,3)
        else:
            worker.join(40)
        if worker.is_alive():
            handle.cancel()
            record.update(status="failed",error_code="VALIDATION_THREAD_STILL_RUNNING")
        record.update(latency_ms=round((time.monotonic()-started)*1000,3),
            sdk_attempts=adapter.request_attempts,request_body_fields=sent_fields,
            sdk_clients_closed=all(c.is_closed() for c in clients),worker_finished=not worker.is_alive(),
            cancellation=handle.public_info())
        if manual:
            record["raw_body_preserved"] = bool(body_matches) and all(body_matches)
        records.append(record)
        # Never automatically repeat or escalate a failed request.
        if worker.is_alive():
            break
    return {"date":"2026-10-02","retry":0,"maximum_generation_requests":4,"cases":records}


def main():
    parser = argparse.ArgumentParser(description="受控真实验证，最多四次生成请求，retry=0。")
    parser.add_argument("--confirm-real-network", action="store_true")
    args = parser.parse_args()
    if not args.confirm_real_network:
        print("NETWORK_CONFIRMATION_REQUIRED")
        return 2
    try:
        data = run_validation()
    except Exception:
        print("VALIDATION_SETUP_ERROR")
        return 1
    destination = Path.cwd() / "outputs/access-modes-validation.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # JSON output is restricted to public counters/status. No raw prompt or completion.
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
