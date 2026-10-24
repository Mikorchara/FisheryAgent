"""QQ protocol tests: MockTransport only, fictional credentials, no external I/O."""
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from contextlib import redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import Mock

import httpx
from apps.qq_bot.adapter import GroupReply
from apps.qq_bot.contracts import BotError
from apps.qq_bot.transport import GatewayURLRejected, QQAPI, gateway_url


class QQAPITests(unittest.TestCase):
    def setUp(self):
        self.requests, self.now = [], 100.0
        self.responses = []
        self.snapshot = Mock()
        self.snapshot._for_adapter.return_value = 'fictional-secret'
        self.supplier = Mock(return_value=self.snapshot)
        def handler(request):
            self.requests.append(request)
            if request.url.path == '/app/getAppAccessToken':
                return httpx.Response(200, json={'access_token': 'fictional-token', 'expires_in': '7200'})
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        self.client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(self.client.close)
        self.api = QQAPI('123456789', self.supplier, client=self.client, monotonic=lambda: self.now)
        self.addCleanup(self.api.close)
        self.time = datetime(2026, 10, 24, tzinfo=timezone.utc)
        self.reply = GroupReply('allowed-group', 'ROBOT1.0_fixture', '只读测试')

    def send(self, **options):
        return self.api.reply(self.reply, received_at=options.get('received_at', self.time),
                              now=options.get('now', self.time))

    def test_token_contract_and_cache_refresh_margin(self):
        self.assertEqual(self.api.token(), 'fictional-token')
        request = self.requests[0]
        self.assertEqual(str(request.url), 'https://api.bot.qq.com/app/getAppAccessToken')
        self.assertEqual(json.loads(request.content), {'appId': '123456789', 'clientSecret': 'fictional-secret'})
        self.assertNotIn('authorization', request.headers)
        self.now += 7139
        self.api.token()
        self.assertEqual(len(self.requests), 1)
        self.now += 1
        self.api.token()
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn('fictional-secret', repr(self.api))

    def test_business_error_on_http_200_is_not_success(self):
        self.responses.append(httpx.Response(200, json={'code': 11253, 'message': 'private response'}))
        with self.assertRaisesRegex(BotError, '^QQ_API_11253$'):
            self.api.gateway()

    def test_gateway_authorization_and_url(self):
        self.responses.append(httpx.Response(200, json={'url': 'wss://api.bot.qq.com/websocket/'}))
        self.assertEqual(self.api.gateway(), 'wss://api.bot.qq.com/websocket/')
        self.assertEqual(self.requests[-1].headers['Authorization'], 'QQBot fictional-token')

    def test_legacy_gateway_response_keeps_rest_requests_on_current_api_host(self):
        value = 'wss://api.sgroup.qq.com/websocket/'
        self.responses.append(httpx.Response(200, json={'url': value}))
        self.assertEqual(self.api.gateway(), value)
        self.assertEqual([str(request.url) for request in self.requests], [
            'https://api.bot.qq.com/app/getAppAccessToken', 'https://api.bot.qq.com/gateway'])

    def test_gateway_response_missing_url_and_null_have_distinct_diagnostics(self):
        for response, present, json_type, reason in (
            ({}, False, 'missing', 'GATEWAY_URL_FIELD_MISSING'),
            ({'url': None}, True, 'null', 'GATEWAY_URL_TYPE_INVALID'),
        ):
            self.responses.append(httpx.Response(200, json=response))
            with self.subTest(reason=reason), self.assertRaises(GatewayURLRejected) as caught:
                self.api.gateway()
            diagnostic = caught.exception.diagnostic
            self.assertEqual(caught.exception.code, 'GATEWAY_URL_REJECTED')
            self.assertEqual((diagnostic.stage, diagnostic.url_present, diagnostic.url_type,
                              diagnostic.reason_code), ('response', present, json_type, reason))
            self.assertIsNone(diagnostic.parse_ok)

    def test_gateway_api_uses_fixed_get_path_without_redirects(self):
        self.responses.append(httpx.Response(302, headers={'Location': 'https://untrusted.invalid/fixture'}))
        with self.assertRaisesRegex(BotError, '^QQ_HTTP_302$'):
            self.api.gateway()
        self.assertEqual((self.requests[-1].method, str(self.requests[-1].url)),
                         ('GET', 'https://api.bot.qq.com/gateway'))
        self.assertEqual(len(self.requests), 2)  # Fake token + GET only, no redirect.

    def test_reply_is_one_fresh_passive_text_with_sequence_one(self):
        self.responses.append(httpx.Response(200, json={'id': 'sent-fixture'}))
        self.assertTrue(self.send())
        request = self.requests[-1]
        self.assertEqual(request.url.path, '/v2/groups/allowed-group/messages')
        self.assertEqual(json.loads(request.content), {'msg_type': 0, 'content': '只读测试',
            'msg_id': 'ROBOT1.0_fixture', 'msg_seq': 1})

    def test_expired_and_future_context_cannot_send(self):
        for seconds in (-1, 300, 500):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(BotError, 'REPLY_EXPIRED'):
                self.send(now=self.time+timedelta(seconds=seconds))
        self.assertEqual(self.requests, [])

    def test_invalid_reply_cannot_send(self):
        from dataclasses import replace
        for change in ({'group_id': '../other'}, {'msg_id': ''}, {'msg_seq': 2},
                       {'msg_type': 2}, {'content': ''}, {'content': 'x'*1801}):
            with self.subTest(change=change), self.assertRaises(BotError):
                self.api.reply(replace(self.reply, **change), received_at=self.time, now=self.time)
        self.assertEqual(self.requests, [])

    def test_send_timeout_and_connection_loss_never_retry(self):
        for error in (httpx.ReadTimeout('secret detail'), httpx.RemoteProtocolError('private detail')):
            self.responses.append(error)
            before = len(self.requests)
            with self.assertRaisesRegex(BotError, '^QQ_DELIVERY_UNKNOWN$'):
                self.send()
            self.assertEqual(len(self.requests)-before, 2 if before == 0 else 1)

    def test_permission_rate_redirect_and_unauthorized_fail_closed(self):
        for status in (401, 403, 429, 302):
            self.responses.append(httpx.Response(status, headers={'Location': 'https://untrusted.invalid'},
                                                 text='do not expose'))
            with self.subTest(status=status), self.assertRaisesRegex(BotError, '^QQ_HTTP_'+str(status)+'$'):
                self.send()
        self.assertTrue(all(r.url.host == 'api.bot.qq.com' for r in self.requests))
        self.assertEqual(sum(r.url.path == '/app/getAppAccessToken' for r in self.requests), 2)

    def test_no_confirmed_send_id_is_not_reported_success(self):
        self.responses.append(httpx.Response(200, json={}))
        with self.assertRaisesRegex(BotError, '^QQ_SEND_NOT_CONFIRMED$'):
            self.send()

    def test_invalid_large_and_duplicate_response(self):
        for response in (httpx.Response(200, content=b'x'*65537), httpx.Response(200, text='<html>'),
                         httpx.Response(200, text='{"url":1,"url":2}')):
            self.responses.append(response)
            with self.assertRaises(BotError):
                self.api.gateway()

    def test_invalid_token_responses_and_missing_secret(self):
        for value in ({'code': 5}, {'access_token': 'a', 'expires_in': True},
                      {'access_token': 'a\nb', 'expires_in': 7200}, {'access_token': 'a', 'expires_in': 7201}):
            with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=value))) as client:
                with self.subTest(value=value), self.assertRaises(BotError):
                    QQAPI('123456789', self.supplier, client=client).token()
        self.snapshot._for_adapter.return_value = None
        with self.assertRaisesRegex(BotError, 'QQ_SECRET_MISSING_OR_INVALID'):
            self.api.token()
        self.assertEqual(self.requests, [])

    def test_gateway_allowlist_rejects_redirected_insecure_or_token_urls(self):
        for value in ('ws://api.bot.qq.com/websocket/', 'wss://evil.invalid/websocket/',
                      'wss://api.bot.qq.com:444/websocket/', 'wss://user@api.bot.qq.com/websocket/',
                      'wss://api.bot.qq.com/websocket/?token=a', 'wss://api.bot.qq.com/other', None):
            with self.subTest(value=value), self.assertRaisesRegex(BotError, 'GATEWAY_URL_REJECTED'):
                gateway_url(value)


class GatewayDiagnosticTests(unittest.TestCase):
    def rejected(self, value):
        with self.assertRaises(GatewayURLRejected) as caught:
            gateway_url(value)
        self.assertEqual(caught.exception.code, 'GATEWAY_URL_REJECTED')
        return caught.exception

    def test_known_allowed_forms_return_exact_original_and_log_nothing(self):
        output = StringIO()
        with redirect_stdout(output):
            for host in ('api.bot.qq.com', 'api.sgroup.qq.com'):
                for value in (f'wss://{host}/websocket/', f'wss://{host}/websocket',
                              f'wss://{host}:443/websocket/', f'wss://{host.upper()}/websocket/'):
                    with self.subTest(value=value):
                        self.assertEqual(gateway_url(value), value)
        self.assertEqual(output.getvalue(), '')

    def test_gateway_hosts_are_exact_not_subdomains_suffixes_or_lookalikes(self):
        for host in ('sub.api.bot.qq.com', 'sub.api.sgroup.qq.com', 'api.bot.qq.com.evil.invalid',
                     'api.sgroup.qq.com.evil.invalid', 'api-bot.qq.com', 'api-sgroup.qq.com',
                     'api.sgroup.qq.com.', 'sandbox.api.sgroup.qq.com', 'bots.qq.com',
                     'api.sgroup.qq.com@evil.invalid', '127.0.0.1'):
            with self.subTest(host=host):
                diagnostic = self.rejected(f'wss://{host}/websocket/').diagnostic
                self.assertEqual(diagnostic.reason_code, 'GATEWAY_URL_POLICY_REJECTED')
                self.assertFalse(diagnostic.hostname_matches)

    def test_other_url_restrictions_apply_equally_to_both_gateway_hosts(self):
        for host in ('api.bot.qq.com', 'api.sgroup.qq.com'):
            for value in (f'ws://{host}/websocket/', f'https://{host}/websocket/',
                          f'wss://{host}:444/websocket/', f'wss://{host}/other/',
                          f'wss://fixture-user@{host}/websocket/',
                          f'wss://fixture-user:fixture-password@{host}/websocket/',
                          f'wss://{host}/websocket/?fixture=1', f'wss://{host}/websocket/#fixture'):
                with self.subTest(value=value):
                    diagnostic = self.rejected(value).diagnostic
                    self.assertEqual(diagnostic.reason_code, 'GATEWAY_URL_POLICY_REJECTED')
                    self.assertTrue(diagnostic.hostname_matches)

    def test_connector_keeps_allowed_host_and_default_tls_verification(self):
        import importlib.util
        from unittest.mock import patch
        from apps.qq_bot.transport import connect_gateway
        if importlib.util.find_spec('websockets') is None:
            self.skipTest('optional QQ dependency not installed')
        with patch('websockets.sync.client.connect') as connect:
            for host in ('api.bot.qq.com', 'api.sgroup.qq.com'):
                value = f'wss://{host}/websocket/'
                connect_gateway(value)
                self.assertEqual(connect.call_args.args, (value,))
                # No custom SSL context or hostname override; library WSS defaults remain.
                self.assertNotIn('ssl', connect.call_args.kwargs)
                self.assertNotIn('server_hostname', connect.call_args.kwargs)
                self.assertIsNone(connect.call_args.kwargs['proxy'])

    def test_each_json_type_has_fixed_label_and_is_not_parsed_as_a_url(self):
        for value, expected in ((None, 'null'), (True, 'boolean'), (False, 'boolean'), (42, 'number'),
                                (1.5, 'number'), ({'private': 'fixture'}, 'object'),
                                (['private-fixture'], 'array'), (b'fixture', 'non_json')):
            with self.subTest(expected=expected):
                diagnostic = self.rejected(value).diagnostic
                self.assertEqual((diagnostic.reason_code, diagnostic.url_present, diagnostic.url_type),
                                 ('GATEWAY_URL_TYPE_INVALID', True, expected))
                self.assertIsNone(diagnostic.parse_ok)
                self.assertIsNone(diagnostic.scheme_matches)

    def test_url_parse_failure_suppresses_exception_details(self):
        error = self.rejected('wss://[PRIVATE-PARSE-FIXTURE/websocket/')
        self.assertEqual(error.diagnostic.reason_code, 'GATEWAY_URL_PARSE_FAILED')
        self.assertFalse(error.diagnostic.parse_ok)
        self.assertIsNone(error.diagnostic.port_parse_ok)
        self.assertIsNone(error.diagnostic.hostname_matches)
        self.assertNotIn('PRIVATE', repr(error))
        self.assertTrue(error.__suppress_context__)

    def test_invalid_port_is_separate_from_url_parse_failure(self):
        for port in ('PRIVATE-PORT-FIXTURE', '65536', '-1'):
            with self.subTest(port=port):
                diagnostic = self.rejected('wss://api.bot.qq.com:'+port+'/websocket/').diagnostic
                self.assertEqual(diagnostic.reason_code, 'GATEWAY_URL_PORT_INVALID')
                self.assertTrue(diagnostic.parse_ok)
                self.assertFalse(diagnostic.port_parse_ok)
                self.assertIsNone(diagnostic.port_matches)
                self.assertTrue(diagnostic.hostname_matches)

    def test_each_policy_mismatch_is_visible_without_raw_component(self):
        for value, field in (
            ('ws://api.bot.qq.com/websocket/', 'scheme_matches'),
            ('wss://private-host.invalid/websocket/', 'hostname_matches'),
            ('wss://api.bot.qq.com:444/websocket/', 'port_matches'),
            ('wss://api.bot.qq.com/private-path-fixture/', 'path_matches'),
            ('wss://api.bot.qq.com/websocket//', 'path_matches'),
        ):
            with self.subTest(field=field):
                diagnostic = self.rejected(value).diagnostic
                self.assertEqual(diagnostic.reason_code, 'GATEWAY_URL_POLICY_REJECTED')
                self.assertTrue(diagnostic.parse_ok)
                self.assertTrue(diagnostic.port_parse_ok)
                self.assertFalse(getattr(diagnostic, field))
                self.assertNotIn(value, json.dumps(asdict(diagnostic)))

    def test_all_sensitive_components_are_only_booleans(self):
        error = self.rejected('wss://PRIVATE-USER:PRIVATE-PASSWORD@api.bot.qq.com/websocket/'
                              '?access_token=PRIVATE-TOKEN#PRIVATE-FRAGMENT')
        diagnostic = asdict(error.diagnostic)
        for field in ('has_username', 'has_password', 'has_query', 'has_fragment'):
            self.assertIs(diagnostic[field], True)
        for field in ('scheme_matches', 'hostname_matches', 'port_matches', 'path_matches'):
            self.assertIs(diagnostic[field], True)
        self.assertNotIn('PRIVATE', json.dumps(diagnostic))
        self.assertEqual(str(error), 'GATEWAY_URL_REJECTED')

    def test_input_controls_and_whitespace_are_flags_not_normalization(self):
        value = 'wss://api.bot.qq.com/private\x00 fixture'
        diagnostic = self.rejected(value).diagnostic
        self.assertTrue(diagnostic.input_has_whitespace)
        self.assertTrue(diagnostic.input_has_controls)
        self.assertFalse(diagnostic.path_matches)
        self.assertNotIn('fixture', json.dumps(asdict(diagnostic)))

    def test_structural_rejection_does_not_open_websocket(self):
        import importlib.util
        from unittest.mock import patch
        from apps.qq_bot.transport import connect_gateway
        if importlib.util.find_spec('websockets') is None:
            self.skipTest('optional QQ dependency not installed')
        with patch('websockets.sync.client.connect') as connect:
            with self.assertRaises(GatewayURLRejected):
                connect_gateway('wss://untrusted.invalid/websocket/')
        connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
