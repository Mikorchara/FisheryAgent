"""Exact managed-content source variant, with no inherited qualification.

Only fixed data-source fields change; matchers, runtime scopes, budgets,
startup flags and null qualification records retain their existing values.
"""
from dataclasses import replace
import json

from apps.knowledge.service import CONTENT_SOURCE, CONTENT_VERSION
from apps.ai_backend.model_gateway import GatewayError


def content_scope_configs(execution, streaming, unified):
    def binding(value):
        if (value.get('knowledge_source')!='legacy:eel_knowledge.json' or
                value.get('knowledge_version')!='1.0' or value.get('retrieval_backend')!='portable'):
            raise GatewayError('KNOWLEDGE_CONTENT_SCOPE_MISMATCH')
        return {**value,'knowledge_source':CONTENT_SOURCE,'knowledge_version':CONTENT_VERSION}
    def encoded(value):
        return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    def scope(raw):
        value=json.loads(raw)
        value['data_bindings']=binding(value['data_bindings'])
        return encoded(value)
    execution=replace(execution,releases=tuple(replace(r,data_bindings_json=encoded(binding(json.loads(r.data_bindings_json))))
                                              for r in execution.releases))
    streaming=replace(streaming,releases=tuple(replace(r,data_bindings_json=encoded(binding(json.loads(r.data_bindings_json))))
                                              for r in streaming.releases))
    unified=replace(unified,normal_scope_json=scope(unified.normal_scope_json),streaming_scope_json=scope(unified.streaming_scope_json))
    return execution,streaming,unified
