"""Local-only, explicitly approved Hybrid research. No QQ publication authority."""
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import time

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ModelExecutionStep, ToolExecutionStep
from .channel_hybrid import hybrid_scope, HybridHistorySnapshot
from .channel_session_run import SessionQwenTurn, TurnLease, memory_sdk_factory
from .channel_trial import QwenTrialApproval, TrialQwenAdapter, PRESET, cost_reservation
from .channel_validation import ValidationBoundary, implementation_sha256
from .runtime.release_contracts import _hash

CONTRACT = 'local-qwen-hybrid-research@1'


def research_scope(profile, policy, registry, options):
    base = hybrid_scope(profile, policy, registry, options)
    root = Path(__file__).resolve().parents[2]
    paths = ('apps/ai_service/channel_hybrid_research.py', 'apps/qq_bot/hybrid_research.py',
             'apps/qq_bot/hybrid_research_cli.py', 'apps/qq_bot/hybrid_research_suite.py',
             'apps/qq_bot/resources/hybrid_research_questions.json',
             'scripts/dev/Test-HybridProvider.ps1')
    return {**base, 'contract': CONTRACT, 'environment': 'EXPLICIT_LOCAL_PROVIDER_RESEARCH',
        'publication': 'LOCAL_CONTROLLED_REVIEW_ONLY_NO_QQ',
        'history_acceptance': 'LOCAL_CAPTURE_NOT_QQ_DELIVERY@1',
        'batch': {'max_cases': 50, 'max_repetitions': 5, 'max_runs': 50,
                  'independent_run_max_turns': 5, 'resume': False, 'refund': False,
                  'failure_policy': 'STOP_BATCH_BEFORE_NEXT_MODEL_REQUEST'},
        'approval': 'LIVE_PROCESS_TYPED_RUNCONSENT_NO_OLD_APPROVALS@1',
        'research_implementation': {p: implementation_sha256(root/p) for p in paths}}


def prepared_scope(options):
    from apps.ai_backend.tools import ToolDefinition, ToolRegistry
    from apps.ai_backend.tools.policy import ToolPolicy
    from .business_tools.current_water_quality import WATER_DEFINITION
    from .runtime.assistant import assistant_profile
    return research_scope(assistant_profile(PRESET),
        ToolPolicy('assistant', True, ('get_current_water_quality',)),
        ToolRegistry((ToolDefinition(WATER_DEFINITION, lambda: None),)), options)


def preparation_record(scope):
    return dict(schema_version=1, contract=CONTRACT, status='candidate', scope=scope,
        scope_sha256=_hash(scope), qualification_id=None,
        real_execution_requires='NEW_LOCAL_PROCESS_OPERATOR_APPROVAL',
        qq_publication_authorized=False, old_approvals_accepted=False)


@dataclass(frozen=True, repr=False)
class ResearchAuthorization:
    authority: object
    ticket: object
    consent_id: str
    scope_sha256: str
    bindings_sha256: str
    lease_authority: object


class ResearchAuthority:
    """Live identity, never deserialized from JSON or a model message."""
    def __init__(self, check):
        self.check = check
        self.current = None
        self.boundary = ValidationBoundary()

    def issue(self, **fields):
        if self.current is not None:raise GatewayError('RESEARCH_ALREADY_APPROVED')
        self.current = ResearchAuthorization(self, object(), **fields)
        return self.current

    def validate(self, value):
        if type(value) is not ResearchAuthorization or value is not self.current or value.authority is not self:
            raise GatewayError('RESEARCH_APPROVAL_REQUIRED')
        with self.boundary.scope():self.check(value)


class TimedResearchAdapter(TrialQwenAdapter):
    """Observes the original SDK Adapter; this mixed interval includes cleanup/checks."""
    def complete(self, request, runtime):
        start = time.monotonic()
        code = None
        try:return super().complete(request, runtime)
        except Exception as error:
            from apps.ai_backend.assistant_activity import safe_code
            code = safe_code(getattr(error, 'code', None)) or 'MODEL_REQUEST_FAILED'
            raise
        finally:
            self.trial.model_timings.append(dict(
                adapter_total_ms=round((time.monotonic()-start)*1000, 3),
                http_only_ms=None, interval='MIXED_SDK_PERMISSION_IO_CLEANUP', code=code))


class ResearchHybridTurn(SessionQwenTurn):
    release_status = 'local_experimental'

    def __init__(self, lease, *, run_authorization, authority, conversation_epoch, options,
                 snapshot, validate, claim, async_client_factory=None, clock=None, monotonic=None):
        if type(lease) is not TurnLease or type(run_authorization) is not ResearchAuthorization:
            raise GatewayError('RESEARCH_APPROVAL_REQUIRED')
        run_authorization.authority.validate(run_authorization)
        lease.authority.validate(lease)
        if (lease.authority is not run_authorization.lease_authority
                or lease.scope_sha256 != run_authorization.scope_sha256
                or lease.bindings_sha256 != run_authorization.bindings_sha256
                or not lease.approval_id.startswith(run_authorization.consent_id+'-')
                or snapshot.identity[:5] != (lease.app_id, lease.group_id, lease.member_id,
                                           lease.instance_id, lease.device_id)):
            raise GatewayError('RESEARCH_LEASE_MISMATCH')
        self.run_authorization, self.lease = run_authorization, lease
        self.authority, self.conversation_epoch = authority, conversation_epoch
        self.options, self.snapshot = options, snapshot
        self.model_timings, self.execution_metadata = [], {}
        self.raw_text = None
        # The legacy QQ phase check must fail even for an approved real local turn.
        approval = QwenTrialApproval(lease.approval_id, 'provider', lease.scope_sha256,
            lease.bindings_sha256, lease.expires_at, str(cost_reservation()),
            lease.instance_id, lease.device_id, lease.app_id, lease.group_id, lease.member_id)
        def check():
            run_authorization.authority.validate(run_authorization)
            lease.authority.validate(lease)
            validate()
        factory = memory_sdk_factory(async_client_factory) if async_client_factory is not None else None
        kwargs = {} if monotonic is None else {'monotonic': monotonic}
        self._initialize(approval, validate=check, claim=claim, async_client_factory=factory,
                         clock=clock, **kwargs)
        self.adapter = TimedResearchAdapter(self, async_client_factory=factory)

    def check(self):
        with self.run_authorization.authority.boundary.scope():return super().check()

    def history_decision(self, profile, policy, registry, authorization, snapshot, *, epoch, policy_revision):
        if type(snapshot) is not HybridHistorySnapshot:raise GatewayError('INVALID_HYBRID_HISTORY')
        with self.run_authorization.authority.boundary.scope():
            self.check()
            return self._bound_history_decision(profile, policy, registry, authorization, snapshot,
                epoch=epoch, policy_revision=policy_revision,
                digest=_hash(research_scope(profile, policy, registry, self.options)),
                reason='EXPLICIT_LOCAL_HYBRID_RESEARCH_RUN')

    def inspect_execution(self, result):
        from .hybrid_presentation import _document
        from .channel_presentation import _unique, _not_constant
        self.raw_text = result.final_text
        syntax, envelope = None, None
        if self.raw_text or result.status.value=='completed':syntax, envelope = False, False
        try:
            json.loads(self.raw_text, object_pairs_hook=_unique, parse_constant=_not_constant)
            syntax = True
            _document(self.raw_text)
            envelope = True
        except (ValueError, TypeError, UnicodeError, RecursionError):pass
        tools = [s for s in result.execution.steps if isinstance(s, ToolExecutionStep)]
        models = [s for s in result.execution.steps if isinstance(s, ModelExecutionStep)]
        first=models[0].result if models else None
        requested=(bool(tools) or first is not None and (first.outcome in
            ('tool_calls','multiple_tool_calls','tool_round_limit') or first.finish_reason in ('tool_calls','function_call')))
        route='water' if requested else 'general' if first is not None and first.outcome=='final_answer' else None
        self.execution_metadata = dict(json_syntax_valid=syntax, envelope_valid=envelope,
            actual_branch='water' if tools else 'general',
            model_route=route, model_outcomes=[m.result.outcome for m in models],
            tool_steps=len(tools), tool_handler_calls=sum(s.handler_started for s in tools),
            tool_results=[dict(name=s.tool_name if s.tool_name=='get_current_water_quality' else 'unauthorized',
                handler_started=s.handler_started, status=s.result.status.value if s.result else None,
                duration_ms=s.duration_ms) for s in tools],
            model_steps=len(models), backend_status=result.status.value,
            backend_error=result.error_code)

    def report(self):
        value = super().report()
        value.pop('source_summary', None)
        value.pop('model_text_displayed', None)
        return {**value, 'execution': self.execution_metadata, 'model_timings': list(self.model_timings),
                'qq_api_accepted': False, 'client_display_confirmed': False,
                'local_research_only': True, 'remote_compute_stopped': 'unknown'}
