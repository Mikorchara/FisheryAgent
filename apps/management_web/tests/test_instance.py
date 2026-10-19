"""MIG-2: isolated data lifecycle, composition and management-only packaging."""
import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import tomllib
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from apps.management_paths import ManagementPaths
from apps.management_web import __main__ as entry
from apps.management_web.instance import initialize_instance, validate_instance, InstanceError
from apps.monitoring.repository import MonitoringRepository
from apps.knowledge.repository import KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from scripts.dev import local_session

ROOT = Path(__file__).resolve().parents[3]


class InstanceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paths = ManagementPaths.resolve(self.root, data_root=self.root/'instance')

    def test_legacy_paths_and_explicit_user_data_do_not_touch_files(self):
        legacy = ManagementPaths.resolve(self.root)
        self.assertEqual(legacy.monitoring, self.root/'outputs/management_web/monitoring.sqlite3')
        self.assertEqual(legacy.knowledge, self.root/'apps/knowledge_data/knowledge.sqlite3')
        self.assertEqual(legacy.settings, self.root/'outputs/management_web/settings.json')
        self.assertEqual(legacy.policy_directory, self.root/'outputs/tool-policies')
        self.assertEqual(legacy.traces, self.root/'outputs/management_web/assistant-traces.jsonl')
        selected = ManagementPaths.resolve(self.root, user_data=True, environment={'LOCALAPPDATA':str(self.root)})
        self.assertEqual(selected.data_root, self.root/'FisheryManagement')
        self.assertFalse(selected.data_root.exists())
        for options in ({'data_root':'relative'}, {'user_data':True,'environment':{}},
                        {'data_root':self.root,'user_data':True}):
            with self.assertRaises(ValueError): ManagementPaths.resolve(self.root, **options)

    def test_missing_instance_refuses_without_any_creation_or_legacy_fallback(self):
        with self.assertRaisesRegex(InstanceError,'MONITORING_DATABASE_MISSING'):
            validate_instance(self.paths)
        self.assertFalse(self.paths.data_root.exists())
        with patch.object(entry, 'project_root', return_value=self.root), \
                patch('apps.monitoring.repository.MonitoringRepository') as repository, \
                self.assertRaises(SystemExit):
            entry.main(['--data-root',str(self.paths.data_root)])
        repository.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_explicit_initialize_is_complete_empty_and_never_overwrites(self):
        initialize_instance(self.paths)
        validate_instance(self.paths)
        self.assertEqual(KnowledgeRepository(self.paths.knowledge,require_existing=True).snapshot()[1], [])
        self.assertEqual(MonitoringRepository(self.paths.monitoring,require_existing=True).history('pond-a','water'), [])
        self.assertTrue(self.paths.policy_directory.is_dir())
        self.assertTrue(self.paths.traces.parent.is_dir())
        for path in (self.paths.settings,self.paths.traces): self.assertFalse(path.exists())
        before = self.paths.knowledge.read_bytes()
        with self.assertRaisesRegex(InstanceError,'INSTANCE_ALREADY_EXISTS'): initialize_instance(self.paths)
        self.assertEqual(self.paths.knowledge.read_bytes(),before)

    def test_init_failure_cleans_private_staging_and_publishes_nothing(self):
        from apps.knowledge.repository import KnowledgeError
        for failure, code in ((OSError('fictional'),'INSTANCE_STORAGE_ERROR'),
                (sqlite3.OperationalError('fictional'),'INSTANCE_STORAGE_ERROR'),
                (KnowledgeError('KNOWLEDGE_STORAGE_ERROR'),'KNOWLEDGE_STORAGE_ERROR')):
            with self.subTest(code=code), patch('apps.knowledge.repository.KnowledgeRepository',side_effect=failure), \
                    self.assertRaisesRegex(InstanceError,code):
                initialize_instance(self.paths)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_racing_publication_keeps_the_other_instance(self):
        import apps.management_web.instance as instance
        original = instance.validate_instance
        def competing(paths):
            original(paths)
            self.paths.data_root.mkdir()
            (self.paths.data_root/'sentinel').write_text('fictional',encoding='utf-8')
        with patch.object(instance,'validate_instance',side_effect=competing), \
                self.assertRaisesRegex(InstanceError,'INSTANCE_ALREADY_EXISTS'):
            initialize_instance(self.paths)
        self.assertEqual((self.paths.data_root/'sentinel').read_text(), 'fictional')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['instance'])

    def test_missing_knowledge_does_not_create_other_files_on_startup(self):
        self.paths.data_root.mkdir()
        MonitoringRepository(self.paths.monitoring)
        before = self.paths.monitoring.read_bytes()
        with self.assertRaisesRegex(InstanceError,'KNOWLEDGE_DATABASE_MISSING'): validate_instance(self.paths)
        self.assertEqual(self.paths.monitoring.read_bytes(),before)
        self.assertEqual(sorted(p.name for p in self.paths.data_root.iterdir()), ['monitoring.sqlite3'])

    def test_corrupt_and_schema_incompatible_are_distinct_and_read_only(self):
        initialize_instance(self.paths)
        for kind,path in (('MONITORING',self.paths.monitoring),('KNOWLEDGE',self.paths.knowledge)):
            original = path.read_bytes()
            for content,code in ((b'not sqlite', 'CORRUPT'),(b'', 'CORRUPT')):
                path.write_bytes(content)
                with self.assertRaisesRegex(InstanceError,kind+'_DATABASE_'+code): validate_instance(self.paths)
                self.assertEqual(path.read_bytes(),content)
            path.write_bytes(original)
            with closing(sqlite3.connect(path)) as db, db: db.execute('PRAGMA user_version=999')
            before = path.read_bytes()
            with self.assertRaisesRegex(InstanceError,kind+'_DATABASE_SCHEMA_INCOMPATIBLE'): validate_instance(self.paths)
            self.assertEqual(path.read_bytes(),before)
            path.write_bytes(original)

    def test_same_version_incomplete_schema_and_unpublished_knowledge_rejected(self):
        initialize_instance(self.paths)
        with closing(sqlite3.connect(self.paths.knowledge)) as db, db:
            db.execute("DELETE FROM knowledge_metadata WHERE key='migration_version'")
        with self.assertRaisesRegex(InstanceError,'KNOWLEDGE_DATABASE_SCHEMA_INCOMPATIBLE'): validate_instance(self.paths)
        with closing(sqlite3.connect(self.paths.monitoring)) as db, db: db.execute('DROP TABLE current')
        with self.assertRaisesRegex(InstanceError,'MONITORING_DATABASE_SCHEMA_INCOMPATIBLE'): validate_instance(self.paths)

    def test_rw_repository_does_not_recreate_disappearing_database(self):
        initialize_instance(self.paths)
        repository = MonitoringRepository(self.paths.monitoring,require_existing=True)
        self.paths.monitoring.unlink()
        with self.assertRaises(sqlite3.OperationalError): repository.read('pond-a','water')
        self.assertFalse(self.paths.monitoring.exists())
        knowledge = KnowledgeRepository(self.paths.knowledge,require_existing=True)
        self.paths.knowledge.unlink()
        from apps.knowledge.repository import KnowledgeError
        with self.assertRaises(KnowledgeError): knowledge.snapshot()
        self.assertFalse(self.paths.knowledge.exists())

    def test_cli_init_exits_without_http_ai_or_credential_access(self):
        import io
        with patch.object(entry,'project_root',return_value=self.root),patch('sys.stderr',new_callable=io.StringIO), \
                self.assertRaises(SystemExit):
            entry.main(['--data-root',str(self.paths.data_root),'--init-data','--port','0'])
        self.assertFalse(self.paths.data_root.exists())
        with patch.object(entry,'project_root',return_value=self.root), patch.object(entry,'create_app') as app:
            entry.main(['--data-root',str(self.paths.data_root),'--init-data'])
        app.assert_not_called()
        validate_instance(self.paths)

    def test_new_root_settings_policy_trace_and_credential_identity_are_separate(self):
        from apps.ai_service.service import ManagementAssistantService
        with patch.object(ManagementAssistantService,'__init__',return_value=None) as construct, \
                patch('apps.ai_service.runtime.locations.private_project_location') as location, \
                patch('apps.ai_service.service.CredentialStore'):
            ManagementAssistantService.local(object(),self.root,data_paths=self.paths,knowledge=object())
        location.assert_called_once_with(self.root.resolve())
        self.assertEqual(construct.call_args.kwargs['policy_directory'],self.paths.policy_directory)
        self.assertEqual(construct.call_args.kwargs['traces'].path,self.paths.traces)
        self.assertFalse(self.paths.data_root.exists())

    def test_explicit_root_cli_opens_only_selected_databases(self):
        initialize_instance(self.paths)
        with patch.object(entry,'project_root',return_value=self.root),patch.object(entry,'create_app') as factory:
            entry.main(['--data-root',str(self.paths.data_root)])
        options=factory.call_args.kwargs
        self.assertEqual(options['data_service'].repository.path,self.paths.monitoring)
        self.assertEqual(options['knowledge_service'].repository.path,self.paths.knowledge)
        factory.return_value.run.assert_called_once_with(host='127.0.0.1',port=8766,debug=False,load_dotenv=False)

    def test_ai_and_settings_share_selected_paths_without_changing_trial_flags(self):
        initialize_instance(self.paths)
        with patch.object(entry,'project_root',return_value=self.root),patch.object(entry,'create_app'), \
                patch('apps.management_web.ai_adapter.ManagementAssistant.local') as ai, \
                patch('apps.ai_service.settings.ManagementSettingsService') as settings:
            entry.main(['--data-root',str(self.paths.data_root),'--enable-assistant',
                        '--assistant-streaming-trial','--assistant-multi-round-trial','--assistant-tools-trial'])
        self.assertEqual(ai.call_args.kwargs['data_paths'],self.paths)
        self.assertTrue(ai.call_args.kwargs['streaming_trial'])
        self.assertTrue(ai.call_args.kwargs['multi_round_trial'])
        self.assertTrue(ai.call_args.kwargs['unified_tools_trial'])
        self.assertFalse(ai.call_args.kwargs['history_trial'])
        self.assertEqual(settings.call_args.args,(ai.return_value.backend,self.paths.settings))

    def test_shared_policy_compatibility_is_local_to_selected_instance(self):
        from apps.ai_service.runtime.policy import UserToolPolicyStore
        from apps.ai_service.management_policy import ManagementToolPolicyStore
        from apps.ai_backend.tools.registry import ToolRegistry
        # Poisoned legacy file must not be opened by the explicit-root composition.
        legacy = ManagementPaths.resolve(self.root)
        legacy.policy_directory.mkdir(parents=True)
        (legacy.policy_directory/'tool_policies.json').write_text('not JSON',encoding='utf-8')
        inherited=UserToolPolicyStore(self.paths.policy_directory,ToolRegistry([]))
        management=ManagementToolPolicyStore(self.paths.policy_directory,inherited)
        defaults=management.snapshot()
        self.assertNotIn('get_water_quality_history',defaults.selected_tools)
        values=inherited.default_selections()
        values['modes']['assistant']['selected_tools']=[]
        inherited.save(values)
        self.assertEqual(management.snapshot().selected_tools,())
        self.assertEqual((legacy.policy_directory/'tool_policies.json').read_text(),'not JSON')

    def test_database_storage_error_and_linked_files_refused_without_writes(self):
        initialize_instance(self.paths)
        from apps.management_web.instance import check_database
        with patch('apps.management_web.instance.sqlite3.connect',side_effect=sqlite3.OperationalError('fictional')):
            with self.assertRaisesRegex(InstanceError,'MONITORING_DATABASE_STORAGE_ERROR'):
                check_database(self.paths.monitoring,'MONITORING')
        linked=self.root/'linked.sqlite3'
        os.link(self.paths.monitoring,linked)
        try:
            with self.assertRaisesRegex(InstanceError,'INSTANCE_UNSAFE_PATH'): validate_instance(self.paths)
        finally:
            linked.unlink()

    def test_real_server_simulator_with_explicit_data_root_and_owned_interrupt_cleanup(self):
        initialize_instance(self.paths)
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0)); port=reserve.getsockname()[1]
        children=[]; started=time.monotonic(); observed=False
        def launch(command,**options):
            self.assertNotIn('PYTHONPATH',options['env'])
            child=subprocess.Popen(command,**options);children.append(child);return child
        def wait(seconds):
            nonlocal observed
            if len(children)==2 and time.monotonic()-started>10:
                with urlopen(f'http://127.0.0.1:{port}/api/monitoring',timeout=1) as response:
                    observed='window_mean' in json.dumps(json.load(response))
                if observed: raise KeyboardInterrupt()
            if time.monotonic()-started>19: raise AssertionError('no simulator report')
            time.sleep(seconds)
        with patch.dict(os.environ,{'PYTHONPATH':'nonexistent-legacy-path'}):
            self.assertEqual(local_session.run_local('normal',port,root=ROOT,assistant=False,
                data_root=self.paths.data_root,launch=launch,sleep=wait,emit=lambda _:None),0)
        self.assertTrue(observed)
        self.assertTrue(all(child.poll() is not None for child in children))
        self.assertTrue(self.paths.monitoring.is_file())

    def test_management_build_template_and_staging_exclude_runtime_and_prototype(self):
        spec=importlib.util.spec_from_file_location('management_build',ROOT/'scripts/packaging/prepare_management.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        # Use a workspace-local temporary directory as the build contract requires.
        with TemporaryDirectory(dir=ROOT/'outputs') as directory:
            target=Path(directory)/'stage';module.prepare(target)
            metadata=tomllib.loads((target/'pyproject.toml').read_text())
            self.assertEqual(metadata['build-system']['requires'],['setuptools>=68'])
            self.assertEqual(metadata['project']['requires-python'],'>=3.11')
            original=tomllib.loads((ROOT/'pyproject.toml').read_text())
            self.assertEqual(metadata['project']['dependencies'],original['project']['dependencies'])
            self.assertFalse((target/'src').exists())
            self.assertFalse((target/'apps/knowledge_data').exists())
            self.assertFalse(list(target.rglob('*.sqlite3')))
            self.assertFalse(list(target.rglob('test_*.py')))
            for package in ('ai_service/resources','ai_service/runtime/resources','management_web/static'):
                expected={p.name:p.read_bytes() for p in (ROOT/'apps'/package).iterdir() if p.is_file()}
                self.assertEqual(expected,{p.name:p.read_bytes() for p in (target/'apps'/package).iterdir()})
            with self.assertRaises(FileExistsError): module.prepare(target)

    def test_no_old_package_http_sse_fake_sdk_paths_in_fresh_isolated_process(self):
        code = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,*args):
  if fullname=='fishery_ai' or fullname.startswith('fishery_ai.'):
   raise AssertionError('PROTOTYPE_FORBIDDEN')
sys.meta_path.insert(0,Block())
from apps.ai_service.tests.capture_migration import capture
result=capture()
assert len(result)==6 and all(v['committed'] and v['resources_closed'] for v in result.values())
assert not any(n=='fishery_ai' or n.startswith('fishery_ai.') for n in sys.modules)
'''
        run=subprocess.run([sys.executable,'-I','-c',f'import sys;sys.path.insert(0,{str(ROOT)!r})\n'+code],
            cwd=self.root,capture_output=True,text=True,timeout=60)
        self.assertEqual(run.returncode,0,run.stderr)


if __name__ == '__main__': unittest.main()
