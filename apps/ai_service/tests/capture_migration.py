"""Offline HTTP migration fingerprint helper; never called by application startup.

Run in a separate process before/after the atomic migration. Retain hashes only,
never prompts, parameters, result bodies or credentials. All inputs are fictional.
"""

from apps.knowledge.tests.support import reference_knowledge
from dataclasses import asdict
from datetime import datetime, timezone
import importlib
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.ai_backend.tests.support import FakeSDK, sdk_tool, sdk_final, tool_chunks, final_chunks
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app
from apps.ai_service.service import ManagementAssistantService
from apps.ai_service.execution import load_execution_config
from apps.ai_service.streaming import load_streaming_config
from apps.monitoring.service import MonitoringService
from apps.monitoring.repository import MonitoringRepository
from apps.simulator.generator import Simulator

WATER='get_current_water_quality'
KNOWLEDGE='search_fishery_knowledge'
PRESET='dashscope-qwen38-flash-r1'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,
        separators=(',',':')).encode()).hexdigest()


def stable(value):
    if isinstance(value,dict):
        return {k:stable(v) for k,v in value.items() if k not in (
            'request_id','trace_id','completed_at','duration_ms','total_latency_ms')}
    if isinstance(value,(tuple,list)):return [stable(v) for v in value]
    return value


def capture():
    prefix='apps.ai_backend'
    assistant=importlib.import_module('apps.ai_service.runtime.assistant')
    adapter=importlib.import_module(prefix+'.openai_compatible_adapter').OpenAICompatibleAdapter
    credentials=importlib.import_module(prefix+'.credentials').CredentialStore
    traces=importlib.import_module(prefix+'.observability').JsonlTraceSink
    guard=importlib.import_module('apps.ai_backend.tests.test_execution')
    fixture=unittest.TestCase();guard.ExecutionTests.setUp(fixture)
    output={}
    try:
        for transport in ('normal','streaming'):
            for path in ('direct','single','double'):
                with TemporaryDirectory() as directory:
                    root=Path(directory);clock=[datetime(2026,10,16,tzinfo=timezone.utc)]
                    monitoring=MonitoringService(MonitoringRepository(root/'db.sqlite3'),
                        device_names={'pond-a':'Fixture'},clock=lambda:clock[0])
                    batch=Simulator(start=clock[0],session_id='migration',device_id='pond-a',seed=42).advance()
                    clock[0]=datetime.fromisoformat(batch['timestamp'])
                    batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2,min=2.2,max=2.2,latest=2.2)
                    monitoring.ingest(batch)
                    if transport=='normal':
                        plans=[sdk_final()] if path=='direct' else [sdk_tool(WATER),sdk_final()] if path=='single' else [
                            sdk_tool(WATER),sdk_tool(KNOWLEDGE,'call_2','{"query":"鳗鲡低氧表现"}'),sdk_final()]
                    else:
                        plans=[final_chunks()] if path=='direct' else [tool_chunks(WATER),final_chunks()] if path=='single' else [
                            tool_chunks(WATER),tool_chunks(KNOWLEDGE,'call_2','{"query":"鳗鲡低氧表现"}'),final_chunks()]
                    profile=assistant.assistant_profile(PRESET)
                    sdk=FakeSDK(plans,model=profile.model)
                    sink=traces(root/'trace',tool_names=(WATER,KNOWLEDGE))
                    service=ManagementAssistantService(monitoring,
            knowledge=reference_knowledge(),credentials=credentials(process_env={
                        profile.credential_ref:'fictional-migration-credential'}),traces=sink,
                        policy_directory=root/'policy',gateway_factory=lambda:adapter(async_client_factory=sdk.factory),
                        execution_config=load_execution_config(enable_trial=True),
                        streaming_config=load_streaming_config(enable_trial=True))
                    service.epoch='fixed-migration-epoch'
                    policy=service.policy_store.default_selections();policy['modes']['assistant']['selected_tools']=[WATER,KNOWLEDGE]
                    service.policy_store.save(policy)
                    ai=ManagementAssistant(service);app=create_app(data_service=monitoring,ai=ai);client=app.test_client()
                    bootstrap=client.get('/api/ai/bootstrap?device=pond-a').get_json()
                    headers={'X-Management-AI':bootstrap['browser_token']}
                    control=client.post('/api/ai/requests',json={'epoch':service.epoch},headers=headers).get_json()
                    revision=bootstrap['presets'][0]['streaming']['revision'] if transport=='streaming' else bootstrap['presets'][0]['revision']
                    body={**control,'epoch':service.epoch,'preset_id':PRESET,'device_id':'pond-a',
                        'question':'隔离迁移测试','history':[],'revision':revision,'confirm_network':True}
                    results=[];original=assistant.AssistantService.send
                    def collect(owner,request,runtime):
                        result=original(owner,request,runtime);results.append(result);return result
                    with patch.object(assistant.AssistantService,'send',collect):
                        response=client.post('/api/ai/messages'+('/stream' if transport=='streaming' else ''),json=body,headers=headers)
                        if transport=='streaming':
                            events=[json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith('data: ')]
                            value=events[-1]['result']
                        else:value=response.get_json()['result']
                    response.close()
                    assert value['successful_turn'],value.get('error_code')
                    output[transport+'-'+path]={'protocol_sha256':digest(sdk.bodies),
                        'safe_dto_sha256':digest(stable(value)),
                        'ledger_sha256':digest(results[0].source_ledger.to_dict()),
                        'steps_sha256':digest(stable([asdict(s) for s in results[0].execution.steps])),
                        'revision':revision,'request_count':len(sdk.bodies),
                        'usage':value['usage'],'committed':value['successful_turn'],
                        'resources_closed':all(c.closed and (c.stream is None or c.stream.closed) for c in sdk.clients)}
    finally:fixture.doCleanups()
    return output


if __name__=='__main__':
    print(json.dumps(capture(),sort_keys=True,indent=2))
