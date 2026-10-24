from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from apps.ai_backend.credentials import CredentialStore
from apps.qq_bot.cli import main
from apps.qq_bot.configuration import SECRET_REF, load_access, save_secret, secret_supplier
from apps.qq_bot.contracts import BotError
from apps.qq_bot.offline import network_blocked


class ConfigurationCLITests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root/'access.json'
        self.value = {'schema_version': 1, 'app_id': '123456789', 'groups': [
            {'group_id': 'fictional-group', 'device_id': 'sim-pond-1', 'members': ['fictional-member'],
             'capabilities': ['current', 'history', 'knowledge', 'events']}]}
        self.write()
        guard = network_blocked(); guard.__enter__(); self.addCleanup(guard.__exit__, None, None, None)

    def write(self):
        self.path.write_text(json.dumps(self.value), encoding='utf-8')

    def cli(self, *args):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(list(args))
        return result, output.getvalue(), errors.getvalue()

    def test_access_file_exact_schema_and_frozen_bindings(self):
        config = load_access(self.path)
        self.assertEqual(config.app_id, '123456789')
        self.assertEqual(config.groups[0].members, ('fictional-member',))
        self.assertEqual(config.member_per_minute, 6)

    def test_secret_unknown_fields_invalid_app_duplicates_and_write_capabilities_rejected(self):
        for edit in (lambda: self.value.update(app_secret='fictional'),
                     lambda: self.value.update(app_id='not-a-qq-app'),
                     lambda: self.value.update(schema_version=True),
                     lambda: self.value['groups'][0].update(capabilities=['ack']),
                     lambda: self.value['groups'][0].update(members=['x', 'x'])):
            original = json.loads(json.dumps(self.value))
            edit(); self.write()
            with self.assertRaises(BotError):
                load_access(self.path)
            self.value = original
        self.path.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
        with self.assertRaises(BotError):
            load_access(self.path)

    def test_check_config_performs_no_credential_read_and_no_network(self):
        with patch('apps.qq_bot.cli.secret_supplier', side_effect=AssertionError('no credentials')):
            code, output, _ = self.cli('--check-config', '--access-file', str(self.path))
        self.assertEqual(code, 0)
        self.assertIn('QQ_ACCESS_CONFIG_VALID', output)
        self.assertNotIn('fictional-group', output)

    def test_network_requires_explicit_confirmation_and_fictional_or_help_mode(self):
        for args in (['--connect', '--access-file', str(self.path), '--help-only'],
                     ['--connect', '--access-file', str(self.path), '--confirm-qq-network'],
                     ['--discover', '--app-id', '123456789'],
                     ['--connect', '--confirm-qq-network', '--help-only'],
                     ['--discover', '--app-id', '123456789', '--confirm-qq-network', '--fictional-data'],
                     ['--configure-secret', '--replace-secret', '--access-file', str(self.path)]):
            with self.subTest(args=args), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                main(args)

    def test_rejects_real_data_root_llm_and_secret_command_line_arguments(self):
        for option in ('--data-root', '--user-data', '--app-secret', '--enable-ai'):
            with self.subTest(option=option), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                main(['--check-config', '--access-file', str(self.path), option, 'do-not-read'])

    def test_help_only_never_constructs_databases_or_model_and_closes_transport(self):
        with patch('apps.qq_bot.cli.QQAPI') as api, patch('apps.qq_bot.cli.QQGateway') as gateway, \
             patch('apps.qq_bot.cli.secret_supplier', return_value=Mock()), \
             patch('apps.qq_bot.cli.importlib.util.find_spec', return_value=True), \
             patch('apps.qq_bot.offline.seed_fictional', side_effect=AssertionError('no database')):
            code, _, _ = self.cli('--connect', '--access-file', str(self.path), '--help-only',
                                  '--confirm-qq-network', '--run-seconds', '2')
        self.assertEqual(code, 0)
        adapter = gateway.call_args.args[2]
        self.assertEqual(adapter.config.groups[0].capabilities, ())
        self.assertIsNone(adapter._queries._capture)
        self.assertIsNone(adapter._queries._knowledge)
        api.return_value.close.assert_called_once()
        gateway.return_value.run.assert_called_once_with(2)

    def test_live_fictional_queries_use_only_temporary_instances_and_remove_them(self):
        paths = []
        def run_factory(app, api, adapter, **kw):
            from apps.qq_bot.offline import packet
            from datetime import datetime, timezone
            result = adapter.receive(packet('/当前水质', datetime.now(timezone.utc)), transport_app_id=app)
            self.assertEqual(result.code, 'OK')
            self.assertIn('SIMULATOR', result.reply.content)
            result = adapter.receive(packet('/知识 溶解氧', datetime.now(timezone.utc), msg_id='next'), transport_app_id=app)
            self.assertIn('虚构学习资料', result.reply.content)
            paths.append(Path(adapter._queries._capture.__self__.repository.path))
            return Mock()
        with patch('apps.qq_bot.cli.QQAPI'), patch('apps.qq_bot.cli.QQGateway', side_effect=run_factory), \
             patch('apps.qq_bot.cli.secret_supplier', return_value=Mock()), \
             patch('apps.qq_bot.cli.importlib.util.find_spec', return_value=True):
            code, output, _ = self.cli('--connect', '--access-file', str(self.path), '--fictional-data',
                                       '--confirm-qq-network')
        self.assertEqual((code, output), (0, ''))
        self.assertEqual(len(paths), 1)
        self.assertIn('bot1b-', paths[0].parent.name)
        self.assertFalse(paths[0].parent.exists())

    def test_discovery_creates_no_adapter_or_business_services(self):
        with patch('apps.qq_bot.cli.QQAPI'), patch('apps.qq_bot.cli.QQGateway') as gateway, \
             patch('apps.qq_bot.cli.QQAdapter', side_effect=AssertionError('no adapter')), \
             patch('apps.qq_bot.cli.secret_supplier', return_value=Mock()), \
             patch('apps.qq_bot.cli.importlib.util.find_spec', return_value=True):
            code, _, _ = self.cli('--discover', '--app-id', '123456789', '--confirm-qq-network')
        self.assertEqual(code, 0)
        self.assertIsNone(gateway.call_args.args[2])
        self.assertTrue(callable(gateway.call_args.kwargs['discover']))

    def test_discovery_reports_safe_url_diagnostic_and_keeps_legacy_error(self):
        from apps.qq_bot.transport import GatewayURLRejected, gateway_url
        try:
            gateway_url('wss://api.bot.qq.com/websocket/?token=PRIVATE-URL-FIXTURE', stage='response')
        except GatewayURLRejected as error:
            failure = error
        credential = Mock(side_effect=AssertionError('no credential resolution'))
        with patch('apps.qq_bot.cli.QQAPI') as api, \
             patch('apps.qq_bot.cli.secret_supplier', return_value=credential), \
             patch('apps.qq_bot.cli.importlib.util.find_spec', return_value=True):
            api.return_value.app_id = '123456789'
            api.return_value.gateway.side_effect = failure
            code, output, errors = self.cli('--discover', '--app-id', '123456789', '--confirm-qq-network')
        self.assertEqual(code, 1)
        self.assertEqual(errors, '')
        rows = [json.loads(line) for line in output.splitlines()]
        self.assertEqual([row['code'] for row in rows], ['QQ_GATEWAY_CONNECTING', 'QQ_STOPPED',
                         'GATEWAY_URL_POLICY_REJECTED', 'GATEWAY_URL_REJECTED'])
        self.assertTrue(rows[2]['has_query'])
        self.assertEqual(rows[2]['stage'], 'response')
        self.assertNotIn('PRIVATE', output)
        self.assertNotIn('wss://', output)
        self.assertNotIn('Traceback', output)
        credential.assert_not_called()
        api.return_value.close.assert_called_once()

    def test_hidden_secret_input_and_existing_writer_only(self):
        with patch('apps.qq_bot.cli.sys.stdin.isatty', return_value=True), \
             patch('apps.qq_bot.cli.getpass.getpass', return_value='fictional-secret'), \
             patch('apps.qq_bot.cli.save_secret') as save:
            code, output, _ = self.cli('--configure-secret')
        self.assertEqual(code, 0)
        self.assertNotIn('fictional-secret', output)
        self.assertEqual(save.call_args.args[1], 'fictional-secret')
        self.assertEqual(save.call_args.kwargs, {'replace': False})

    def test_nonterminal_secret_prompt_fails_closed(self):
        with patch('apps.qq_bot.cli.sys.stdin.isatty', return_value=False), \
             patch('apps.qq_bot.cli.getpass.getpass', side_effect=AssertionError('must not prompt')):
            code, output, _ = self.cli('--configure-secret')
        self.assertEqual(code, 1)
        self.assertIn('INTERACTIVE_SECRET_PROMPT_REQUIRED', output)

    def test_store_writer_ref_revision_and_no_implicit_overwrite(self):
        store = Mock(private_location=SimpleNamespace(env_path=self.root/'credentials'/'.env'))
        with patch('apps.qq_bot.configuration.ProjectEnvWriter') as writer:
            writer.return_value.inspect.return_value = {'revision': 'opaque', 'exists': False}
            save_secret(self.root, 'fictional-secret', store=store)
            self.assertEqual(writer.call_args.args, (self.root/'credentials', store))
            self.assertFalse(writer.call_args.kwargs['require_git_ignored'])
            kwargs = writer.return_value.mutate.call_args.kwargs
            self.assertEqual((kwargs['action'], kwargs['expected_revision']), ('create', 'opaque'))
            self.assertEqual(writer.return_value.mutate.call_args.args[0], SECRET_REF)
            save_secret(self.root, 'fictional-secret', store=store, replace=True)
            self.assertEqual(writer.return_value.mutate.call_args.kwargs['action'], 'replace')

    def test_secret_ref_uses_existing_store_process_precedence(self):
        store = CredentialStore(process_env={SECRET_REF: 'fictional-env-secret'})
        with patch('apps.qq_bot.configuration.project_credentials', return_value=store):
            snapshot = secret_supplier(self.root)()
        self.assertEqual(snapshot._for_adapter(), 'fictional-env-secret')
        self.assertNotIn('fictional-env-secret', repr(snapshot))

    def test_credential_exception_and_wire_exception_text_are_redacted(self):
        with patch('apps.qq_bot.cli.secret_supplier', side_effect=RuntimeError('fictional-secret private-path')):
            code, output, _ = self.cli('--connect', '--access-file', str(self.path), '--help-only',
                                       '--confirm-qq-network')
        self.assertEqual(code, 1)
        self.assertIn('QQ_START_FAILED', output)
        self.assertNotIn('fictional-secret', output)


if __name__ == '__main__':
    unittest.main()
