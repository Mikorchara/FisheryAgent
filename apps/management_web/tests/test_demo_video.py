"""Local media delivery only; synthetic file bytes, no database/AI/credentials."""
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import unittest
from unittest.mock import patch
from apps.management_web.app import create_app
from apps.management_web.demo_video import LocalDemoVideo, URL
from apps.management_web.services import DemoMonitoring, DemoVideo, DemoEvents
from scripts.dev import local_session,prototype_stack


class DemoVideoTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'fixture.mp4'
        self.bytes=b'\x00\x00\x00\x18ftypisom'+b'fixture-only'*32
        self.path.write_bytes(self.bytes)

    def test_default_disabled_and_explicit_media_does_not_claim_observation(self):
        services=dict(monitoring=DemoMonitoring(),video=DemoVideo(),events=DemoEvents())
        default=create_app(**services).test_client()
        self.assertEqual(default.get(URL).status_code,404)
        before=default.get('/api/bootstrap').get_json()
        self.assertNotIn('video_preview',before)
        client=create_app(**services,demo_video=LocalDemoVideo.open(self.path)).test_client()
        after=client.get('/api/bootstrap').get_json()
        self.assertEqual(after['video_preview']['kind'],'local_file')
        self.assertNotIn(str(self.path),str(after))
        for key in ('cameras','connections','ai','events'):
            self.assertEqual(after[key],before[key])
        self.assertTrue(all(c['stream_url'] is None for c in after['cameras']))

    def test_range_head_and_seek_with_content_type_and_no_path_parameter(self):
        client=create_app(demo_video=LocalDemoVideo.open(self.path)).test_client()
        for method,headers,code in [('get',{},200),('get',{'Range':'bytes=0-15'},206),('head',{},200)]:
            response=getattr(client,method)(URL,headers=headers)
            self.assertEqual(response.status_code,code)
            self.assertEqual(response.mimetype,'video/mp4')
            self.assertIn("media-src 'self'",response.headers['Content-Security-Policy'])
            if code==206:
                self.assertEqual(response.data,self.bytes[:16]);self.assertIn('bytes 0-15/',response.headers['Content-Range'])
            response.close()
        response=client.get(URL+'?path=private.env');self.assertEqual(response.data,self.bytes);response.close()
        self.assertEqual(client.get(URL,headers={'Range':'bytes=99999-'}).status_code,416)
        self.assertEqual(self.path.read_bytes(),self.bytes)

    def test_remote_access_hosts_changes_and_missing_files_fail_closed(self):
        client=create_app(demo_video=LocalDemoVideo.open(self.path)).test_client()
        self.assertEqual(client.get(URL,environ_overrides={'REMOTE_ADDR':'192.0.2.3'}).status_code,403)
        self.assertEqual(client.get(URL,base_url='http://evil.invalid').status_code,403)
        self.assertEqual(client.get(URL,headers={'Origin':'http://evil.invalid'}).status_code,403)
        self.path.write_bytes(self.bytes+b'changed')
        self.assertEqual(client.get(URL).status_code,409)
        self.path.unlink()  # Disposable fixture only.
        self.assertEqual(client.get(URL).status_code,409)

    def test_invalid_file_and_cli_are_rejected_before_business_composition(self):
        from apps.management_web.__main__ import main
        for path in (self.path.with_suffix('.env'),self.path.parent,self.path.parent/'absent.mp4'):
            with self.assertRaisesRegex(ValueError,'LOCAL_DEMO_MP4_REQUIRED'):LocalDemoVideo.open(path)
        self.path.write_bytes(b'not a video')
        with self.assertRaisesRegex(ValueError,'LOCAL_DEMO_MP4_REQUIRED'):LocalDemoVideo.open(self.path)
        with patch('apps.monitoring.repository.MonitoringRepository') as repository,patch('sys.stderr',new=io.StringIO()):
            with self.assertRaises(SystemExit):main(['--demo-video',str(self.path)])
        repository.assert_not_called()

    def test_launch_flags_are_web_only_and_default_path_is_unchanged(self):
        web,sim=local_session.commands('python','normal',8766,42,demo_video=self.path)
        self.assertEqual(web[web.index('--demo-video')+1],str(self.path))
        self.assertNotIn('--demo-video',sim)
        self.assertNotIn('--demo-video',local_session.commands('python','normal',8766,42)[0])
        with patch.object(prototype_stack,'launch_stack',return_value=0) as launch:
            self.assertEqual(prototype_stack.main(['--demo-video',str(self.path)]),0)
        self.assertEqual(launch.call_args.kwargs['demo_video'],self.path)
