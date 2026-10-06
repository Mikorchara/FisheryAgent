"""One selected published Preset; explicit network consent, no auto publisher."""

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json

from fishery_ai.credential_paths import private_project_location, CredentialLocationError
from fishery_ai.credentials import CredentialStore, CredentialFileError
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import GatewayError, ProfileRegistry
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.preset_tool_qualification import qualify_preset_tools
from fishery_ai.presets import preset_profiles
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tools import ToolRegistry


def main():
    parser=argparse.ArgumentParser(description="单个 Preset Tool 资格验证，最多3次请求，不自动发布")
    parser.add_argument("--preset-id",required=True)
    parser.add_argument("--confirm-network",action="store_true")
    args=parser.parse_args()
    if not args.confirm_network:
        print("NETWORK_CONFIRMATION_REQUIRED"); return 2
    root=Path.cwd()
    if not (root / "pyproject.toml").is_file():
        print("WORKSPACE_REQUIRED"); return 2
    profile=next((p for p in preset_profiles() if p.preset_id==args.preset_id and p.preset_variant=="off"),None)
    if profile is None:
        print("PRESET_NOT_FOUND"); return 2
    identity=[profile.service_id,profile.adapter_id,profile.base_url,profile.model]
    report={"preset_id":profile.preset_id,"identity":identity,"protocol_spec_id":profile.preset_protocol_spec.spec_id,
        "contract_version_before":profile.preset_contract_version,"validated_at":datetime.now(timezone.utc).isoformat(),
        "snapshot":"EMPTY_QUALIFICATION_PROCESS","validation_source":"MAINTAINER_PRESET_QUALIFICATION",
        "result":{"verdict":"UNKNOWN","error_code":None,"model_requests":0,"transport_attempts":0}}
    handle=RequestHandle()
    try:
        location=private_project_location(root)
        credentials=CredentialStore(location.env_path,private_location=location)
        runtime=ProfileRegistry([profile],credentials).snapshot(profile.profile_id)
        reader=CurrentWaterQualityReader(CurrentSnapshotStore(),stale_after_s=300)
        registry=ToolRegistry(reader,DiagnosisService())
        traces=JsonlTraceSink(root / "outputs/preset-qualification/tool-traces.jsonl")
        handle.start()
        with request_scope(handle):
            report["result"]=qualify_preset_tools(OpenAICompatibleAdapter(),profile,runtime,registry,traces)
        handle.finish(report["result"]["error_code"])
    except (CredentialFileError,CredentialLocationError):
        report["result"]["error_code"]="CREDENTIAL_FILE_ERROR"
    except GatewayError as exc:
        report["result"]["error_code"]=exc.code
    except Exception:
        report["result"]["error_code"]="QUALIFICATION_FAILED"
    folder=root / "outputs/preset-qualification"
    folder.mkdir(parents=True,exist_ok=True)
    filename=profile.preset_id+"-tools-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")+".json"
    (folder/filename).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))
    return 0 if report["result"]["verdict"]=="SUPPORTED" else 1


if __name__=="__main__": raise SystemExit(main())
