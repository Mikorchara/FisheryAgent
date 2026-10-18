"""Local management preferences and fixed-provider credential operations; no model I/O."""
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid

from apps.ai_backend.credentials import CredentialFileError
from apps.ai_backend.project_env import EnvWriteError, ProjectEnvWriter
from apps.ai_backend.tools.policy import ToolPolicyError
from .management_policy import _check_path, _writer_lock, _unique_object
from .runtime.assistant import assistant_profile
from .service import PRESETS
from .business_tools.fishery_knowledge import TOP_K, MAX_TEXT_CHARS


class SettingsError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class PreferencesStore:
    """Small non-secret JSON/CAS file in existing ignored management output storage."""
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.lock = threading.RLock()

    def read(self):
        try:
            _check_path(self.path)
            try:
                with self.path.open('rb') as stream:
                    raw = stream.read(8193)
            except FileNotFoundError:
                return None
            value = json.loads(raw, object_pairs_hook=_unique_object)
            if len(raw) > 8192 or not isinstance(value, dict) or set(value) != {'schema_version','preferences'} or type(value['schema_version']) is not int or value['schema_version'] != 1:
                raise ValueError()
            return value['preferences']
        except (OSError, ValueError, TypeError, RecursionError, ToolPolicyError):
            raise SettingsError('SETTINGS_STORAGE_ERROR') from None

    def save(self, preferences, *, check):
        with self.lock:
            temporary = self.path.with_name('.settings-' + uuid.uuid4().hex + '.tmp')
            created = False
            try:
                _check_path(self.path)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with _writer_lock(self.path.with_suffix('.lock')):
                    check()
                    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
                        created = True
                        json.dump({'schema_version':1,'preferences':preferences}, stream, ensure_ascii=False, allow_nan=False)
                        stream.flush(); os.fsync(stream.fileno())
                    os.replace(temporary, self.path)
            except SettingsError:
                raise
            except ToolPolicyError as error:
                raise SettingsError('SETTINGS_BUSY' if error.code=='TOOL_POLICY_BUSY' else 'SETTINGS_STORAGE_ERROR') from None
            except (OSError, ValueError):
                raise SettingsError('SETTINGS_STORAGE_ERROR') from None
            finally:
                if created:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass


class ManagementSettingsService:
    # Client chooses a fixed service identifier, never a filename or environment name.
    CLOUDS = {'dashscope':'dashscope-qwen38-flash-r1', 'deepseek':'deepseek-flash-r1'}

    def __init__(self, backend, preferences_path):
        self.backend = backend
        self.store = PreferencesStore(preferences_path)
        credential = backend.credentials
        self.writer = (ProjectEnvWriter(credential.project_env_path.parent, credential,
                       require_git_ignored=False) if credential.private_location is not None else None)

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
                modes[transport] = {**execution,
                    'max_output_tokens':execution['max_output_tokens'] if execution['max_output_tokens'] is not None else profile.default_generation.max_output_tokens,
                    'deadline_s':profile.total_timeout_s, 'retry':profile.max_retries,
                    'output_field':profile.preset_protocol_spec.max_output_tokens_field,
                    'editable':False, 'approved_token_options':[]}
                if execution['can_send'] and type(modes[transport]['max_output_tokens']) is int:
                    modes[transport]['approved_token_options'] = [modes[transport]['max_output_tokens']]
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
            status = self.backend.credentials.status(profile.credential_ref,profile.auth_spec).public_info()
            if self.writer is not None and status['editable']:
                state = self.writer.inspect(profile.credential_ref,profile.auth_spec)
                return {'provider':provider, **status, **state}
            return {'provider':provider, **status, 'editable':False, 'revision':None, 'exists':status['availability']=='PRESENT'}
        except (CredentialFileError, EnvWriteError):
            return {'provider':provider,'availability':'UNAVAILABLE','source':'UNAVAILABLE',
                    'editable':False,'revision':None,'exists':False,'error_code':'CREDENTIAL_STORAGE_UNAVAILABLE'}

    def change_credential(self, value):
        if (not isinstance(value,dict) or set(value) != {'epoch','provider','action','revision','secret','confirm_clear'}
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
        profile = assistant_profile(self.CLOUDS[provider])
        self.writer.mutate(profile.credential_ref,profile.auth_spec,
            action='remove' if value['action']=='remove' else 'replace' if current['exists'] else 'create',
            expected_revision=value['revision'],secret=value['secret'])
        return self.credential_status(provider)
