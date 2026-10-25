"""Real SDK classes + in-memory HTTP; no real key, DNS, Provider or business data."""
import asyncio
from dataclasses import replace
import json
import threading
import unittest

import httpx
from openai import AsyncOpenAI

from apps.ai_backend.contracts import Mode
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import RequestHandle,request_scope
from apps.ai_backend.model_gateway import GatewayError,ModelRequest,ProfileRegistry
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.tests import test_execution as backend_fixture
from apps.ai_service.runtime.assistant import assistant_profile
from apps.qq_bot.ai_configuration import PRESET


class ProviderSDKPreparationTests(unittest.TestCase):
    def setUp(self):
        backend_fixture.ExecutionTests.setUp(self)  # Socket denial; permits only asyncio's internal wakeup pair.
        profile=assistant_profile(PRESET)
        self.runtime=replace(ProfileRegistry([profile],CredentialStore(process_env={
            profile.credential_ref:'fictional-offline-sdk-only'})).snapshot(profile.profile_id),
            transport_output_token_limit=512)
        self.clients=[];self.requests=[]

    def adapter(self,responder):
        def factory(runtime,remaining):
            sdk=AsyncOpenAI(api_key='fictional-offline-sdk-only',base_url=runtime.base_url,max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(responder),trust_env=False))
            self.clients.append(sdk);return sdk
        return OpenAICompatibleAdapter(async_client_factory=factory)

    def good(self):
        return httpx.Response(200,json={'id':'fixture','object':'chat.completion','created':0,
            'model':self.runtime.model,'choices':[{'index':0,'message':{'role':'assistant','content':'fixture'},
            'finish_reason':'stop'}],'usage':{'prompt_tokens':8,'completion_tokens':3,'total_tokens':11}})

    def run_cancel(self,*,body=False):
        started,closed=threading.Event(),threading.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                started.set()
                await asyncio.Event().wait()
                yield b''
            async def aclose(self):closed.set()
        async def responder(request):
            self.requests.append(json.loads(request.content))
            if body:return httpx.Response(200,stream=Body())
            try:
                started.set();await asyncio.Event().wait()
            finally:closed.set()
        adapter=self.adapter(responder);handle=RequestHandle();handle.start();handle.limit_turn(5)
        errors=[];before={t.ident for t in threading.enumerate() if t.name=='fishery-sdk-request'}
        def execute():
            with request_scope(handle):
                try:adapter.complete(ModelRequest(Mode.CHAT,()),self.runtime)
                except GatewayError as error:errors.append(error.code);handle.finish(error.code)
        thread=threading.Thread(target=execute,name='sdk-preparation-test',daemon=False);thread.start()
        try:
            self.assertTrue(started.wait(2));handle.cancel();thread.join(3)
        finally:
            handle.cancel();handle.abort_io();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,['USER_CANCELLED'])
        self.assertTrue(closed.is_set());self.assertTrue(handle.io_closed)
        self.assertTrue(all(c.is_closed() for c in self.clients));self.assertEqual(adapter.request_attempts,1)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(before,{t.ident for t in threading.enumerate() if t.name=='fishery-sdk-request'})
        self.assertEqual(handle.public_info()['remote_compute_stopped'],'unknown')

    def test_actual_sdk_header_wait_is_cancelled_and_client_closes(self):self.run_cancel()
    def test_actual_sdk_body_wait_is_cancelled_and_client_closes(self):self.run_cancel(body=True)

    def test_actual_sdk_deadline_closes_io_without_retry(self):
        closed=threading.Event()
        async def responder(request):
            try:await asyncio.Event().wait()
            finally:closed.set()
        adapter=self.adapter(responder);handle=RequestHandle();handle.start();handle.limit_turn(.5)
        with request_scope(handle),self.assertRaises(GatewayError) as error:
            adapter.complete(ModelRequest(Mode.CHAT,()),self.runtime)
        self.assertEqual(error.exception.code,'TOTAL_TIMEOUT');self.assertTrue(closed.is_set())
        self.assertTrue(handle.io_closed);self.assertEqual(adapter.request_attempts,1)
        self.assertTrue(all(c.is_closed() for c in self.clients))

    def test_actual_qwen_encoding_uses_fixed_identity_no_retry_and_bounded_output(self):
        async def responder(request):
            self.requests.append(json.loads(request.content));return self.good()
        adapter=self.adapter(responder);handle=RequestHandle();handle.start();handle.limit_turn(2)
        with request_scope(handle):
            for _ in range(2):self.assertEqual(adapter.complete(ModelRequest(Mode.CHAT,()),self.runtime).text,'fixture')
        self.assertEqual(len(self.requests),2);self.assertEqual(adapter.request_attempts,2)
        for body in self.requests:
            self.assertEqual(body['model'],'qwen3.8-flash');self.assertEqual(body['max_tokens'],512)
            self.assertFalse(body['enable_thinking']);self.assertFalse(body.get('stream',False))
        self.assertTrue(all(c.is_closed() for c in self.clients));self.assertTrue(handle.io_closed)

    def test_actual_sdk_http_failure_has_no_implicit_retry(self):
        async def responder(request):
            self.requests.append(True);return httpx.Response(503,json={'error':{'message':'fixture'}})
        adapter=self.adapter(responder);handle=RequestHandle();handle.start()
        with request_scope(handle),self.assertRaises(GatewayError):
            adapter.complete(ModelRequest(Mode.CHAT,()),self.runtime)
        self.assertEqual(len(self.requests),1);self.assertEqual(adapter.request_attempts,1)
        self.assertTrue(all(c.is_closed() for c in self.clients))


if __name__=='__main__':unittest.main()
