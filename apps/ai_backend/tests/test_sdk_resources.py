"""Resource failure is not cancellation/success; all wedged fake I/O is released here."""
import asyncio
from dataclasses import replace
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

from apps.ai_backend.execution import RequestHandle,RequestRegistry,request_scope
from apps.ai_backend.model_gateway import GatewayError,ModelRequest
from apps.ai_backend.contracts import Mode
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.sdk_resources import SDKResourceBudget
from apps.ai_backend.tests import test_execution as fixture


def response():
    return NS(choices=[NS(message=NS(content='provisional',tool_calls=()),finish_reason='stop')],usage=None)


class SDKResourceTests(unittest.TestCase):
    def setUp(self):
        fixture.ExecutionTests.setUp(self)
        self.runtime=replace(self.runtime,max_retries=0)
        self.budget=SDKResourceBudget(limit=1)

    def adapter(self,client,*,grace=.08,budget=None):
        return OpenAICompatibleAdapter(async_client_factory=lambda *_:client,
            resource_budget=budget or self.budget,cleanup_timeout_s=grace)

    def call(self,adapter,handle):
        with request_scope(handle):return adapter.complete(ModelRequest(Mode.CHAT,()),self.runtime)

    def async_call(self,adapter,handle):
        outcome=[]
        def execute():
            try:outcome.append(self.call(adapter,handle))
            except GatewayError as error:outcome.append(error.code);handle.finish(error.code)
        thread=threading.Thread(target=execute,name='resource-test-caller',daemon=False)
        thread.start();return thread,outcome

    def release(self,handle,gate,caller=None):
        gate.set();handle.cancel();handle.abort_io()
        if caller is not None:caller.join(3);self.assertFalse(caller.is_alive())
        lease=handle._sdk_resource
        if lease is not None and lease.thread is not None:
            lease.thread.join(3);self.assertFalse(lease.thread.is_alive())

    def test_normal_completion_reports_three_distinct_resource_facts(self):
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):return response()
            async def close(self):pass
        handle=RequestHandle()
        self.assertEqual(self.call(self.adapter(Client()),handle).text,'provisional')
        info=handle.resource_info()
        self.assertEqual(info['state'],'CLOSED');self.assertTrue(info['local_io_closed'])
        self.assertTrue(info['thread_exited']);self.assertTrue(info['task_done'])
        self.assertFalse(info['cancel_signal_sent']);self.assertEqual(info['remote_compute_stopped'],'unknown')
        self.assertEqual(self.budget.snapshot(),dict(active=0,quarantined=0,limit=1))

    def test_repeated_cancel_and_abort_do_not_interrupt_cooperative_close(self):
        started,closing=threading.Event(),threading.Event();counts=[]
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):started.set();await asyncio.Event().wait()
            async def close(self):closing.set();await asyncio.sleep(.02);counts.append(1)
        handle=RequestHandle();adapter=self.adapter(Client(),grace=1)
        caller,outcome=self.async_call(adapter,handle)
        try:
            self.assertTrue(started.wait(2));handle.cancel();self.assertTrue(closing.wait(1))
            for _ in range(8):handle.cancel();handle.abort_io()
            caller.join(2)
        finally:handle.abort_io();caller.join(2)
        self.assertFalse(caller.is_alive());self.assertEqual(outcome,['USER_CANCELLED'])
        self.assertEqual(counts,[1]);self.assertEqual(handle.resource_info()['state'],'CLOSED')
        self.assertTrue(handle.resource_info()['thread_exited']);self.assertEqual(handle.state,'CANCELLED')

    def test_noncooperative_async_io_fails_closed_and_late_exit_does_not_requalify(self):
        started,gate=threading.Event(),threading.Event()
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):
                started.set()
                while not gate.is_set():
                    try:await asyncio.sleep(.005)
                    except asyncio.CancelledError:pass
                return response()
            async def close(self):pass
        handle=RequestHandle();caller,outcome=self.async_call(self.adapter(Client()),handle)
        try:
            self.assertTrue(started.wait(2));handle.cancel();caller.join(2)
            self.assertEqual(outcome,['SDK_CLEANUP_TIMEOUT'])
            self.assertEqual(handle.state,'FAILED');self.assertEqual(handle.error_code,'SDK_CLEANUP_TIMEOUT')
            info=handle.resource_info()
            self.assertTrue(info['cancel_requested'])
            self.assertTrue(info['cancel_signal_sent']);self.assertFalse(info['local_io_closed'])
            self.assertFalse(info['thread_exited']);self.assertEqual(info['state'],'CLEANUP_FAILED')
            with self.assertRaisesRegex(GatewayError,'SDK_RESOURCE_QUARANTINED'):
                self.call(self.adapter(Client()),RequestHandle())
        finally:self.release(handle,gate,caller)
        self.assertTrue(handle.resource_info()['thread_exited'])
        self.assertTrue(handle.resource_info()['local_io_closed'])
        self.assertEqual(handle.resource_info()['state'],'CLEANUP_FAILED')
        with self.assertRaisesRegex(GatewayError,'SDK_CLEANUP_TIMEOUT'):handle.assert_resources_closed()

    def test_synchronously_blocked_event_loop_is_visible_and_bounded_not_claimed_killed(self):
        started,gate=threading.Event(),threading.Event()
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):started.set();gate.wait();return response()
            async def close(self):pass
        handle=RequestHandle();caller,outcome=self.async_call(self.adapter(Client()),handle)
        try:
            self.assertTrue(started.wait(2));handle.cancel();caller.join(2)
            self.assertEqual(outcome,['SDK_CLEANUP_TIMEOUT'])
            self.assertFalse(handle.resource_info()['thread_exited'])
            self.assertEqual(self.budget.snapshot()['quarantined'],1)
        finally:self.release(handle,gate,caller)

    def test_uncooperative_close_blocks_success_and_new_clients(self):
        closing,gate=threading.Event(),threading.Event()
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):return response()
            async def close(self):
                closing.set()
                while not gate.is_set():
                    try:await asyncio.sleep(.005)
                    except asyncio.CancelledError:pass
        handle=RequestHandle();handle.limit_turn(.3)
        caller,outcome=self.async_call(self.adapter(Client()),handle)
        try:
            self.assertTrue(closing.wait(2));caller.join(2)
            self.assertEqual(outcome,['SDK_CLEANUP_TIMEOUT'])
            self.assertFalse(handle.resource_info()['local_io_closed'])
            self.assertFalse(handle.resource_info()['thread_exited'])
        finally:self.release(handle,gate,caller)

    def test_runner_background_task_can_leave_thread_alive_after_client_closed(self):
        gate=threading.Event()
        async def background():
            while not gate.is_set():
                try:await asyncio.sleep(.005)
                except asyncio.CancelledError:pass
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):asyncio.create_task(background());return response()
            async def close(self):pass
        handle=RequestHandle()
        try:
            with self.assertRaisesRegex(GatewayError,'SDK_CLEANUP_TIMEOUT'):
                self.call(self.adapter(Client()),handle)
            info=handle.resource_info()
            self.assertTrue(info['task_done']);self.assertTrue(info['local_io_closed'])
            self.assertFalse(info['thread_exited'])
        finally:self.release(handle,gate)

    def test_close_exception_is_resource_failure_not_generic_sdk_success_or_cancel(self):
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):return response()
            async def close(self):raise RuntimeError('PRIVATE-FIXTURE-CLOSE')
        handle=RequestHandle()
        with self.assertRaisesRegex(GatewayError,'SDK_CLEANUP_FAILED') as error:
            self.call(self.adapter(Client()),handle)
        self.assertNotIn('PRIVATE',str(error.exception));handle.finish(error.exception.code)
        self.assertEqual(handle.state,'FAILED');self.assertFalse(handle.resource_info()['local_io_closed'])
        self.assertTrue(handle.resource_info()['thread_exited'])
        handle.cancel()
        self.assertTrue(handle.resource_info()['cancel_requested'])
        self.assertEqual(handle.state,'FAILED')
        record=Mock()
        with self.assertRaisesRegex(GatewayError,'SDK_CLEANUP_FAILED'):handle.finalize_result(record)
        record.assert_not_called()

    def test_same_budget_rejects_fresh_adapter_handle_and_direct_sdk_calls_after_failure(self):
        lease=self.budget.reserve();lease.opening();lease.settle()
        factory=Mock(side_effect=AssertionError('must not create another client'))
        adapter=OpenAICompatibleAdapter(client_factory=factory,async_client_factory=factory,resource_budget=self.budget)
        for operation in (lambda:adapter.complete(ModelRequest(Mode.CHAT,()),self.runtime),
                          lambda:list(adapter.stream(ModelRequest(Mode.CHAT,()),self.runtime)),
                          lambda:self.call(adapter,RequestHandle())):
            with self.assertRaisesRegex(GatewayError,'SDK_RESOURCE_QUARANTINED'):operation()
        factory.assert_not_called();self.assertEqual(adapter.request_attempts,0)

    def test_registry_does_not_prune_or_release_failed_resource_by_terminal_state_or_ttl(self):
        registry=RequestRegistry(limit=1,ttl_s=.001);handle=registry.create();handle.start()
        lease=self.budget.reserve();lease.opening();handle._sdk_resource=lease;lease.settle()
        handle.finish('USER_CANCELLED');time.sleep(.005)
        with self.assertRaisesRegex(GatewayError,'REQUEST_LIMIT_REACHED'):registry.create()
        self.assertIs(registry.get(handle.request_id,handle.control_token),handle)
        self.assertEqual(handle.state,'FAILED')

    def test_global_default_is_shared_across_adapter_instances(self):
        with patch('apps.ai_backend.openai_compatible_adapter.SDK_RESOURCES',self.budget):
            first=OpenAICompatibleAdapter();second=OpenAICompatibleAdapter()
            self.assertIs(first._resources,second._resources)
            lease=first._resources.reserve();lease.opening();lease.settle()
            with self.assertRaisesRegex(GatewayError,'SDK_RESOURCE_QUARANTINED'):
                second.complete(ModelRequest(Mode.CHAT,()),self.runtime)

    def test_active_capacity_is_bounded_and_released_after_confirmed_close(self):
        first=self.budget.reserve()
        with self.assertRaisesRegex(GatewayError,'SDK_RESOURCE_LIMIT'):self.budget.reserve()
        self.assertIsNone(first.settle())
        second=self.budget.reserve();self.assertIsNone(second.settle())

    def test_sdk_thread_start_failure_leaves_no_owned_resources(self):
        handle=RequestHandle();adapter=self.adapter(Mock())
        with patch('apps.ai_backend.openai_compatible_adapter.threading.Thread.start',side_effect=RuntimeError('private')):
            with self.assertRaisesRegex(GatewayError,'SDK_ERROR'):self.call(adapter,handle)
        self.assertTrue(handle.resource_info()['thread_exited'])
        self.assertEqual(self.budget.snapshot()['quarantined'],0)

    def test_cancel_before_any_sdk_resources_has_no_lease_or_model_request(self):
        handle=RequestHandle();handle.cancel();factory=Mock()
        with self.assertRaisesRegex(GatewayError,'USER_CANCELLED'):self.call(self.adapter(factory),handle)
        self.assertIsNone(handle.resource_info());factory.assert_not_called()

    def test_sdk_reporting_open_after_close_return_cannot_succeed(self):
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):return response()
            async def close(self):pass
            def is_closed(self):return False
        handle=RequestHandle()
        with self.assertRaisesRegex(GatewayError,'SDK_CLEANUP_FAILED'):
            self.call(self.adapter(Client()),handle)
        self.assertFalse(handle.resource_info()['local_io_closed'])
        self.assertTrue(handle.resource_info()['thread_exited'])

    def test_stop_during_success_close_finishes_cancelled_with_clean_local_resources(self):
        closing,gate=threading.Event(),threading.Event();counts=[]
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):return response()
            async def close(self):
                closing.set()
                while not gate.is_set():await asyncio.sleep(.005)
                counts.append(1)
        handle=RequestHandle();caller,outcome=self.async_call(self.adapter(Client(),grace=1),handle)
        try:
            self.assertTrue(closing.wait(2));handle.cancel();gate.set();caller.join(2)
        finally:self.release(handle,gate,caller)
        self.assertEqual(outcome,['USER_CANCELLED']);self.assertEqual(counts,[1])
        self.assertEqual(handle.state,'CANCELLED');self.assertEqual(handle.resource_info()['state'],'CLOSED')

    def test_stop_after_confirmed_final_cannot_reopen_or_cancel_committed_result(self):
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kw):return response()
            async def close(self):pass
        handle=RequestHandle();self.call(self.adapter(Client()),handle)
        result=NS(error_code=None)
        self.assertIs(handle.finalize_result(lambda cancelled:result),result)
        handle.cancel();handle.abort_io()
        self.assertEqual(handle.state,'COMPLETED');self.assertTrue(handle.resource_info()['thread_exited'])

    def test_admission_observes_detected_failure_before_quarantine_callback_finishes(self):
        lease=self.budget.reserve();lease.opening()
        entered,release=threading.Event(),threading.Event();quarantine=self.budget.quarantine
        def delayed(resource):
            entered.set();release.wait(2);quarantine(resource)
        with patch.object(self.budget,'quarantine',side_effect=delayed):
            thread=threading.Thread(target=lease.settle,daemon=False);thread.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertEqual(lease.snapshot()['state'],'CLEANUP_FAILED')
                with self.assertRaisesRegex(GatewayError,'SDK_RESOURCE_QUARANTINED'):self.budget.reserve()
            finally:release.set();thread.join(2)
        self.assertFalse(thread.is_alive())


if __name__=='__main__':unittest.main()
