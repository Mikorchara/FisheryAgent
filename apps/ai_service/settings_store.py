"""Existing non-secret settings file: atomic CAS for preferences and output overrides."""
import json
import os
from pathlib import Path
import threading
import uuid
from apps.ai_backend.tools.policy import ToolPolicyError
from .management_policy import _check_path, _writer_lock, _unique_object


class SettingsError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class PreferencesStore:
    """Small non-secret JSON/CAS file in existing ignored management output storage."""
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.lock = threading.RLock()

    def document(self):
        try:
            _check_path(self.path)
            try:
                with self.path.open('rb') as stream:
                    raw = stream.read(8193)
            except FileNotFoundError:
                return {'preferences':None,'output_budgets':{},'budget_revision':0}
            value = json.loads(raw, object_pairs_hook=_unique_object)
            if len(raw) > 8192 or not isinstance(value, dict) or type(value.get('schema_version')) is not int:
                raise ValueError()
            if value['schema_version']==1 and set(value)=={'schema_version','preferences'}:
                return {'preferences':value['preferences'],'output_budgets':{},'budget_revision':0}
            if (value['schema_version']!=2 or set(value)!={'schema_version','preferences','output_budgets','budget_revision'}
                    or type(value['budget_revision']) is not int or not 0<=value['budget_revision']<2**53
                    or not isinstance(value['output_budgets'],dict) or len(value['output_budgets'])>2
                    or value['output_budgets'] and value['budget_revision']==0):
                raise ValueError()
            from .output_budget import validate_overrides
            validate_overrides(value['output_budgets'])
            return {k:v for k,v in value.items() if k!='schema_version'}
        except (OSError, ValueError, TypeError, RecursionError, ToolPolicyError):
            raise SettingsError('SETTINGS_STORAGE_ERROR') from None

    def read(self):
        return self.document()['preferences']

    def save(self, preferences, *, check, output_budgets=None):
        with self.lock:
            temporary = self.path.with_name('.settings-' + uuid.uuid4().hex + '.tmp')
            created = False
            try:
                _check_path(self.path)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with _writer_lock(self.path.with_suffix('.lock')):
                    check()
                    current=self.document()
                    revision=current['budget_revision']+(output_budgets is not None)
                    if revision>=2**53:
                        raise SettingsError('SETTINGS_STORAGE_ERROR')
                    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
                        created = True
                        json.dump({'schema_version':2,'preferences':preferences,
                            'output_budgets':current['output_budgets'] if output_budgets is None else output_budgets,
                            'budget_revision':revision}, stream, ensure_ascii=False, allow_nan=False)
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

