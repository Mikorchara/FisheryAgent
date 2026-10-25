"""SDK resource evidence cannot be bypassed by a completed fake AI turn."""
from threading import Event
import unittest
from unittest.mock import patch

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.sdk_resources import SDKResourceBudget
from apps.qq_bot.ai_delivery import DeliveryOwner,OfflineQQGateway
from apps.qq_bot.ai_scheduler import QQAIJobScheduler
from apps.qq_bot.contracts import BotError
from apps.qq_bot.tests import test_ai_coordinator as fixtures

APP=fixtures.APP


class QQSDKResourceGateTests(unittest.TestCase):
    setUp=fixtures.QQAIServiceTests.setUp
    make=fixtures.QQAIServiceTests.make
    packet=fixtures.QQAIServiceTests.packet
    ingest=fixtures.QQAIServiceTests.ingest

    def failed_resource(self,handle):
        lease=SDKResourceBudget().reserve();lease.opening();handle._sdk_resource=lease
        lease.settle();return lease

    def test_source_and_backend_final_do_not_override_unconfirmed_sdk_resource(self):
        plan=self.coordinator.prepare(self.packet(),transport_app_id=APP)
        result=self.coordinator.execute(plan)
        self.assertTrue(result.completed)
        self.failed_resource(plan.handle)
        owner=DeliveryOwner(self.coordinator,OfflineQQGateway(),clock=lambda:self.now)
        with self.assertRaisesRegex(GatewayError,'SDK_CLEANUP_FAILED'):
            self.coordinator.validate_delivery_candidate(plan,result)
        with self.assertRaisesRegex(BotError,'SDK_CLEANUP_FAILED'):
            owner.deliver(plan,result,Event())
        self.assertEqual(len(owner.gateway.posts),0)

    def test_scheduler_preserves_failure_over_cancel_and_refuses_replacement(self):
        gateway=OfflineQQGateway();scheduler=QQAIJobScheduler(self.coordinator,gateway,clock=lambda:self.now)
        execute=self.coordinator.execute
        def unsafe(plan):
            result=execute(plan)
            self.failed_resource(plan.handle)
            scheduler.cancel(plan.id)
            return result
        try:
            with patch.object(self.coordinator,'execute',side_effect=unsafe):
                task=scheduler.submit(self.packet(),transport_app_id=APP)
                done=scheduler.wait(task)
            self.assertEqual((done['state'],done['code']),('FAILED','SDK_CLEANUP_FAILED'))
            self.assertEqual(done['sdk_resources']['state'],'CLEANUP_FAILED')
            with self.assertRaisesRegex(BotError,'AI_RESOURCE_QUARANTINED'):
                scheduler.submit(self.packet(),transport_app_id=APP)
            with self.assertRaisesRegex(BotError,'AI_SDK_RESOURCE_UNSAFE'):scheduler.close()
            self.assertTrue(all(not t.is_alive() for t in scheduler._threads))
            with self.assertRaisesRegex(BotError,'AI_SCHEDULER_ALREADY_BOUND'):
                QQAIJobScheduler(self.coordinator,OfflineQQGateway())
        finally:
            try:scheduler.close()
            except BotError as error:self.assertEqual(error.code,'AI_SDK_RESOURCE_UNSAFE')

    def test_global_sdk_quarantine_error_stops_admission_without_own_lease(self):
        gateway=OfflineQQGateway();scheduler=QQAIJobScheduler(self.coordinator,gateway,clock=lambda:self.now)
        try:
            with patch.object(self.coordinator,'execute',side_effect=BotError('SDK_RESOURCE_QUARANTINED')):
                task=scheduler.submit(self.packet(),transport_app_id=APP)
                self.assertEqual(scheduler.wait(task)['state'],'FAILED')
            with self.assertRaisesRegex(BotError,'AI_RESOURCE_QUARANTINED'):
                scheduler.submit(self.packet(),transport_app_id=APP)
        finally:
            with self.assertRaisesRegex(BotError,'AI_SDK_RESOURCE_UNSAFE'):scheduler.close()
            self.assertTrue(all(not t.is_alive() for t in scheduler._threads))


if __name__=='__main__':unittest.main()
