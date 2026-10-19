"""Management defaults, approved output options and explicitly requested credential checks."""
import hashlib
import json

from apps.ai_backend.credentials import CredentialFileError
from apps.ai_backend.project_env import EnvWriteError, ProjectEnvWriter
from .runtime.assistant import assistant_profile
from .service import PRESETS
from .settings_store import SettingsError, PreferencesStore
from .business_tools.fishery_knowledge import TOP_K, MAX_TEXT_CHARS
from . import output_budget
from .credential_test import CredentialConnectionTests


class ManagementSettingsService:
    # Client chooses a fixed service identifier, never a filename or environment name.
    CLOUDS = {'dashscope':'dashscope-qwen38-flash-r1', 'deepseek':'deepseek-flash-r1'}

    def __init__(self, backend, preferences_path, *, probe_gateway_factory=None):
        self.backend = backend
        self.store = PreferencesStore(preferences_path)
        if backend.settings_store is not None:
            if backend.settings_store.path!=self.store.path:
                raise ValueError('SETTINGS_PATH_MISMATCH')
            self.store=backend.settings_store
        backend.settings_store=self.store
        credential = backend.credentials
        self.writer = (ProjectEnvWriter(credential.project_env_path.parent, credential,
                       require_git_ignored=False) if credential.private_location is not None else None)
        self.connection_tests=CredentialConnectionTests(self,probe_gateway_factory or backend.gateway_factory)

    @staticmethod
    def validate(value):
        if (not isinstance(value, dict) or set(value) != {'preset_id','device_id','transport','show_details'}
                or not isinstance(value['preset_id'],str) or value['preset_id'] not in PRESETS
                or not isinstance(value['device_id'],str) or not 1 <= len(value['device_id']) <= 80
                or value['transport'] not in ('normal','streaming') or type(value['show_details']) is not bool):
            raise SettingsError('INVALID_SETTINGS')
        return dict(value)

    def preferences(self):
        saved = self.store.read()
        if saved is not None:
            return self.validate(saved)
        return {'preset_id':PRESETS[0], 'device_id':self.backend.monitoring.devices()[0]['id'],
                'transport':'normal', 'show_details':True}

    def public(self, *, credentials=True):
        preferences = self.preferences()
        devices = self.backend.monitoring.devices()
        device = preferences['device_id'] if any(d['id']==preferences['device_id'] for d in devices) else devices[0]['id']
        bootstrap = self.backend.bootstrap(device)
        models = []
        for entry in bootstrap['presets']:
            profile = assistant_profile(entry['preset_id'])
            modes = {}
            for transport, key in (('normal','execution'),('streaming','streaming')):
                execution = entry[key]
                budget = execution.get('output_budget', {})
                modes[transport] = {k:v for k,v in execution.items() if k!='output_budget'}
                modes[transport].update({
                    'max_output_tokens':execution['max_output_tokens'] if execution['max_output_tokens'] is not None else profile.default_generation.max_output_tokens,
                    'deadline_s':profile.total_timeout_s, 'retry':profile.max_retries,
                    'output_field':profile.preset_protocol_spec.max_output_tokens_field,
                    'editable':budget.get('editable',False),
                    'approved_token_options':list(budget.get('approved_token_options',[]))})
                if budget.get('editable') is True:
                    modes[transport].update(min_output_tokens=budget['min_output_tokens'],
                        max_allowed_output_tokens=budget['max_allowed_output_tokens'],
                        output_budget_contract=budget['output_budget_contract'],
                        default_output_tokens=budget['default_output_tokens'])
            models.append({'preset_id':entry['preset_id'], 'name':entry['display_name'],
                'provider':profile.service_id,'model_id':profile.model, 'connection':profile.base_url,
                'kind':profile.provider_kind,'thinking':'off',
                'capabilities':{'tool_calling':profile.capabilities.tool_calling.value,
                                'streaming':profile.capabilities.streaming.value}, 'modes':modes})
        body = {'epoch':self.backend.epoch,'preferences':preferences,'devices':devices,'models':models}
        body['revision'] = hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        entry = next(m for m in models if m['preset_id']==preferences['preset_id'])
        body['default_available'] = device == preferences['device_id'] and entry['modes'][preferences['transport']]['can_send']
        body['rag'] = {'method':'TF-IDF', 'read_only':True,'top_k':TOP_K,'max_evidence_chars':MAX_TEXT_CHARS,
            'description':'复用启用知识的不可变索引快照；Top-K 与 Evidence 上限由业务 Tool 固定。'}
        if credentials:
            body['credentials'] = [self.credential_status(name) for name in self.CLOUDS]
        return body

    def save(self, value):
        if not isinstance(value,dict) or set(value) != {'epoch','revision','preferences'}:
            raise SettingsError('INVALID_SETTINGS')
        preferences = self.validate(value['preferences'])
        def check():
            current = self.public(credentials=False)
            if value['epoch'] != current['epoch'] or value['revision'] != current['revision']:
                raise SettingsError('SETTINGS_CHANGED')
            if not any(d['id']==preferences['device_id'] for d in current['devices']):
                raise SettingsError('SETTINGS_DEVICE_UNAVAILABLE')
            candidate = self.backend.bootstrap(preferences['device_id'])
            model = next(m for m in candidate['presets'] if m['preset_id']==preferences['preset_id'])
            if not model['streaming' if preferences['transport']=='streaming' else 'execution']['can_send']:
                raise SettingsError('SETTINGS_MODE_UNAVAILABLE')
        self.store.save(preferences, check=check)
        return self.public()

    def credential_status(self, provider):
        if not isinstance(provider,str) or provider not in self.CLOUDS:
            raise SettingsError('INVALID_CREDENTIAL_PROVIDER')
        profile = assistant_profile(self.CLOUDS[provider])
        try:
            snapshot=self.backend.credentials.resolve(profile.credential_ref,profile.auth_spec)
            status = snapshot.status.public_info()
            status['credential_revision']=snapshot.revision
            if self.writer is not None and status['editable']:
                state = self.writer.inspect(profile.credential_ref,profile.auth_spec)
                return {'provider':provider, **status, **state}
            return {'provider':provider, **status, 'editable':False, 'revision':None, 'exists':status['availability']=='PRESENT'}
        except (CredentialFileError, EnvWriteError, UnicodeError):
            return {'provider':provider,'availability':'UNAVAILABLE','source':'UNAVAILABLE',
                    'editable':False,'revision':None,'credential_revision':None,'exists':False,'error_code':'CREDENTIAL_STORAGE_UNAVAILABLE'}

    def save_budget(self,value):
        if (not isinstance(value,dict) or set(value)!={'epoch','revision','preset_id','transport','action','max_output_tokens'}
                or value['preset_id']!=output_budget.PRESET or value['transport'] not in ('normal','streaming')
                or value['action'] not in ('save','reset')):
            raise SettingsError('INVALID_ASSISTANT_OUTPUT_BUDGET')
        if value['action']=='save':output_budget.validate_tokens(value['max_output_tokens'])
        elif value['max_output_tokens'] is not None:raise SettingsError('INVALID_ASSISTANT_OUTPUT_BUDGET')
        current=self.public(credentials=False)
        selected=next(m for m in current['models'] if m['preset_id']==value['preset_id'])['modes'][value['transport']]
        if not selected['editable']:raise SettingsError('SETTINGS_MODE_UNAVAILABLE')
        overrides=dict(self.store.document()['output_budgets'])
        name=output_budget.key(value['preset_id'],value['transport'])
        if value['action']=='reset':overrides.pop(name,None)
        else:overrides[name]=value['max_output_tokens']
        def check():
            latest=self.public(credentials=False)
            if value['epoch']!=latest['epoch'] or value['revision']!=latest['revision']:
                raise SettingsError('SETTINGS_CHANGED')
        self.store.save(current['preferences'],check=check,output_budgets=overrides)
        return self.public()

    def change_credential(self, value):
        if (not isinstance(value,dict) or set(value)-{'epoch','provider','action','revision','secret','confirm_clear','test_token'}
                or not {'epoch','provider','action','revision','secret','confirm_clear'}<=set(value)
                or value['epoch'] != self.backend.epoch or not isinstance(value['provider'],str) or value['provider'] not in self.CLOUDS
                or value['action'] not in ('save','remove') or type(value['confirm_clear']) is not bool):
            raise SettingsError('INVALID_CREDENTIAL_REQUEST')
        if self.writer is None:
            raise SettingsError('CREDENTIAL_STORAGE_UNAVAILABLE')
        provider = value['provider']
        current = self.credential_status(provider)
        if not current['editable']:
            raise SettingsError('CREDENTIAL_READ_ONLY')
        if value['action']=='remove' and (value['confirm_clear'] is not True or value['secret'] is not None):
            raise SettingsError('CREDENTIAL_CLEAR_CONFIRMATION_REQUIRED')
        if value['action']=='save':
            self.connection_tests.authorize_save(value)
        profile = assistant_profile(self.CLOUDS[provider])
        self.writer.mutate(profile.credential_ref,profile.auth_spec,
            action='remove' if value['action']=='remove' else 'replace' if current['exists'] else 'create',
            expected_revision=value['revision'],secret=value['secret'])
        return self.credential_status(provider)
