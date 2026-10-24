from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.qq_bot.offline import main, network_blocked


class OfflineEntryTests(unittest.TestCase):
    def test_explicit_offline_flag_required_and_no_real_configuration_options(self):
        for arguments in ([], ['--offline-demo', '--data-root', 'C:/private'],
                          ['--offline-demo', '--app-secret', 'not-a-key'],
                          ['--offline-demo', *sum((['--command', '/帮助'] for _ in range(7)), [])]):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(arguments)
            self.assertNotEqual(error.exception.code, 0)

    def test_finite_demo_uses_fictional_databases_removes_temporary_instance_and_never_networks(self):
        from apps.qq_bot import offline
        # Mock only TemporaryDirectory's location: real seeding/queries/parser run.
        original = offline.tempfile.TemporaryDirectory
        with TemporaryDirectory() as parent:
            def temporary(*args, **kwargs):
                kwargs['dir'] = parent
                return original(*args, **kwargs)
            output = io.StringIO()
            with patch.object(offline.tempfile, 'TemporaryDirectory', side_effect=temporary), \
                 network_blocked(), redirect_stdout(output):
                self.assertEqual(main(['--offline-demo']), 0)
            lines = output.getvalue().splitlines()
            results = [json.loads(line) for line in lines[1:]]
            self.assertEqual([r['code'] for r in results[:-1]], ['OK']*5+['AI_DISABLED'])
            self.assertEqual(results[-1]['duplicate'], 'DUPLICATE')
            self.assertEqual(results[-1]['unauthorized_group'], 'GROUP_DENIED')
            self.assertTrue(all(r['mode'] == 'OFFLINE_NOT_SENT' for r in results))
            self.assertEqual(list(Path(parent).iterdir()), [])

    def test_custom_commands_still_use_only_fictional_data(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--offline-demo', '--command', '/历史水质 60']), 0)
        value = json.loads(output.getvalue().splitlines()[1])
        self.assertEqual(value['code'], 'OK'); self.assertIn('最近 60 分钟', value['reply']['content'])

    def test_socket_guard_rejects_network_attempts_and_is_restored(self):
        original = socket.getaddrinfo
        with network_blocked(), self.assertRaisesRegex(RuntimeError, 'BOT_OFFLINE_NETWORK_FORBIDDEN'):
            socket.getaddrinfo('invalid.example', 443)
        self.assertIs(socket.getaddrinfo, original)


if __name__ == '__main__':
    unittest.main()
