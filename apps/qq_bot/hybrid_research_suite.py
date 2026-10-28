"""Versioned research cases and independent <=5-turn Run allocations; no I/O to data."""
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

from apps.ai_service.channel_trial import cost_reservation
from apps.ai_service.runtime.release_contracts import _hash
from .contracts import BotError
from .trial_configuration import read_json

DEFAULT_SUITE = Path(__file__).parent/'resources/hybrid_research_questions.json'


@dataclass(frozen=True)
class ResearchCase:
    id: str
    category: str
    question: str
    expected: str
    dialogue: str | None
    step: int
    rubric: str


def load_suite(path=DEFAULT_SUITE):
    value = read_json(path)
    try:
        if (set(value) != {'schema_version', 'suite_id', 'cases'} or type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['suite_id'] != 'hybrid-research-baseline@1'
                or type(value['cases']) is not list or not 1 <= len(value['cases']) <= 50):raise ValueError()
        cases = tuple(ResearchCase(**v) for v in value['cases'])
        seen, dialogues = set(), {}
        for c in cases:
            if (type(c.id) is not str or not 1<=len(c.id)<=32 or not c.id.isascii() or not c.id.replace('-', '').isalnum()
                    or c.id in seen or c.category not in ('A','B','C','D','E')
                    or c.expected not in ('general','water','ambiguous')
                    or type(c.question) is not str or not c.question.strip()
                    or len(c.question.encode('utf8')) > 2048
                    or type(c.rubric) is not str or not c.rubric
                    or type(c.step) is not int or not 1 <= c.step <= 5
                    or (c.dialogue is None and c.step != 1)):
                raise ValueError()
            seen.add(c.id)
            if c.dialogue is not None:
                if type(c.dialogue) is not str or not c.dialogue.isascii() or len(c.dialogue)>40:raise ValueError()
                dialogues.setdefault(c.dialogue, []).append(c.step)
        if any(steps != list(range(1, len(steps)+1)) for steps in dialogues.values()):raise ValueError()
        return cases
    except (ValueError, TypeError, KeyError):raise BotError('INVALID_RESEARCH_SUITE') from None


def total_money(value):
    try:
        if type(value) is not str or len(value)>32:raise ValueError()
        budget = Decimal(value)
        if not budget.is_finite() or not Decimal('0')<budget<=Decimal('10000'):raise ValueError()
        return budget
    except (ValueError, InvalidOperation):raise BotError('INVALID_EXPERIMENT_BUDGET') from None


def allocate(cases, *, categories=None, case_ids=None, repetitions=1, total_budget_cny=None,
             run_seconds=1800, experiment_seconds=7200):
    if (type(repetitions) is not int or not 1<=repetitions<=5
            or type(run_seconds) is not int or not 1<=run_seconds<=1800
            or type(experiment_seconds) is not int or not 1<=experiment_seconds<=86400):
        raise BotError('INVALID_RESEARCH_LIMITS')
    chosen = tuple(c for c in cases if (not categories or c.category in categories)
                   and (not case_ids or c.id in case_ids))
    if not chosen or (case_ids and set(case_ids)-{c.id for c in cases}):raise BotError('EMPTY_RESEARCH_SELECTION')
    if any(c.dialogue and any(d.dialogue==c.dialogue and d not in chosen for d in cases) for c in chosen):
        raise BotError('RESEARCH_DIALOGUE_MUST_BE_COMPLETE')
    blocks, used = [], set()
    for c in chosen:
        if c.dialogue:
            if c.dialogue in used:continue
            used.add(c.dialogue);blocks.append(tuple(d for d in chosen if d.dialogue==c.dialogue))
        else:blocks.append((c,))
    runs = []
    for repeat in range(1, repetitions+1):
        pending = []
        for block in blocks:
            if len(pending)+len(block)>5:
                runs.append(pending);pending=[]
            pending.extend(dict(case=asdict(c), repetition=repeat) for c in block)
        if pending:runs.append(pending)
    if len(runs)>50:raise BotError('RESEARCH_RUN_LIMIT')
    allocations = []
    for i, entries in enumerate(runs, 1):
        reservation = cost_reservation()*len(entries)
        allocations.append(dict(run=i, entries=entries, max_turns=len(entries), max_model_requests=2*len(entries),
            seconds=run_seconds, reservation_cny=str(reservation),
            budget_cny=str(reservation.quantize(Decimal('.01'), rounding=ROUND_CEILING))))
    minimum = sum((Decimal(r['budget_cny']) for r in allocations), Decimal('0'))
    supplied = total_budget_cny is not None
    budget = total_money(total_budget_cny) if supplied else minimum
    if budget<minimum:raise BotError('EXPERIMENT_BUDGET_INSUFFICIENT')
    return dict(suite_sha256=_hash([asdict(c) for c in cases]), selections=[c.id for c in chosen],
        repetitions=repetitions, runs=allocations, run_count=len(allocations),
        max_turns=len(chosen)*repetitions, max_model_requests=len(chosen)*repetitions*2,
        total_budget_cny=str(budget), budget_explicit=supplied,
        total_run_budgets_cny=str(minimum), reservation_per_turn_cny=str(cost_reservation()),
        experiment_seconds=experiment_seconds, billing_confirmed=False, automatic_retry=False,
        resuming_old_run=False)
