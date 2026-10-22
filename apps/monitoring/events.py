"""Pure event transitions and read projections. SQL and transaction ownership stay outside."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
import uuid

from .contracts import ChannelAnalysis, FindingState
from .rules import VISUAL_RULES


# Local experimental evidence policy, not a professional disease recovery standard.
VISUAL_CLEAR_WINDOWS = 3
VISUAL_RECOVERY_POLICY = "visual-clear-3-v1"


def interrupt_visual(event, reason, at):
    """Withdraw continuity without inventing a CLEAR, closing or replacing an episode."""
    progress = deepcopy(event.get("visual_recovery", {}))
    progress.update(policy_version=VISUAL_RECOVERY_POLICY, required_clear_windows=VISUAL_CLEAR_WINDOWS,
        clear_count=0, last_reliable=False, continuity="interrupted", reason=reason,
        last_interruption_at=at, last_interruption_reason=reason)
    event.update(visual_recovery=progress, lifecycle_state="INDETERMINATE", status="pending",
                 state_reason=reason, assessed_at=at)
    return event


def visual_progress(event, assessment, finding, *, session_id, sequence, fresh_until):
    """Consume one new window. Queries and duplicate/out-of-order batches never call this."""
    previous = event.get("visual_recovery", {})
    ref, quality = assessment.observation, assessment.data_quality
    reliable = quality.quality == "valid" and quality.freshness == "fresh" and quality.connectivity == "online"
    reason = None
    if not reliable:
        reason = finding.reason or "VISUAL_OBSERVATION_NOT_RELIABLE"
    elif not previous or previous.get("policy_version") != VISUAL_RECOVERY_POLICY:
        reason = "CONTINUITY_NOT_ESTABLISHED"
    elif not session_id or previous.get("session_id") != session_id:
        reason = "OBSERVATION_SESSION_CHANGED"
    elif type(sequence) is not int or previous.get("sequence") != sequence - 1:
        reason = "OBSERVATION_SEQUENCE_GAP"
    elif not previous.get("last_reliable"):
        reason = "PREVIOUS_OBSERVATION_NOT_RELIABLE"
    elif datetime.fromisoformat(ref.window_start) != datetime.fromisoformat(previous["window_end"]):
        reason = "OBSERVATION_WINDOW_GAP"
    elif not previous.get("fresh_until") or datetime.fromisoformat(ref.received_at) > datetime.fromisoformat(previous["fresh_until"]):
        reason = "PREVIOUS_OBSERVATION_EXPIRED"
    progress = deepcopy(previous)
    count = (previous.get("clear_count", 0) if reason is None else 0) + 1 if reliable and finding.state == FindingState.CLEAR else 0
    progress.update(policy_version=VISUAL_RECOVERY_POLICY, required_clear_windows=VISUAL_CLEAR_WINDOWS,
        clear_count=min(count, VISUAL_CLEAR_WINDOWS), session_id=session_id, sequence=sequence,
        window_end=ref.window_end, batch_id=ref.batch_id, fresh_until=fresh_until, last_reliable=reliable)
    if reason:
        progress.update(continuity="interrupted", reason=reason,
            last_interruption_at=ref.observed_at, last_interruption_reason=reason,
            segment_started_at=ref.window_start if reliable else None)
    else:
        progress.setdefault("continuity", "continuous")
        progress.setdefault("segment_started_at", ref.window_start)
    if reliable:
        progress["last_valid_observed_at"] = ref.observed_at
    # The first ever HIT starts an episode; no preceding unobserved duration is asserted.
    if not previous and finding.state == FindingState.HIT and reliable and not event.get("id"):
        progress.update(continuity="continuous", reason=None)
        progress.pop("last_interruption_at", None)
        progress.pop("last_interruption_reason", None)
    return progress


@dataclass(frozen=True)
class EventChanges:
    updates: tuple[dict, ...]
    inserts: tuple[dict, ...]
    active_links: tuple[tuple[str, str], ...]
    resolved_codes: tuple[str, ...]


def same_rule(event, finding):
    if finding is None or event["rule_version"] != finding.rule.version:
        return False
    return event.get("rule_identity") is None or (
        json.dumps(event["rule_identity"], sort_keys=True) == json.dumps(finding.to_dict()["rule"], sort_keys=True))


def other_risk(finding, assessment):
    return finding is not None and finding.kind == "WATER_RISK" and any(
        f.kind == "WATER_RISK" and f.state == FindingState.HIT and f.facts_used == finding.facts_used
        for f in assessment.findings)


class EventService:
    def transition(self, existing, assessment, *, id_factory=lambda: uuid.uuid4().hex,
                   session_id=None, sequence=None, fresh_until=None):
        """Compute changes from the active episode set captured inside the write transaction."""
        if not isinstance(assessment, ChannelAnalysis) or assessment.observation is None:
            raise ValueError("INVALID_EVENT_ASSESSMENT")
        if any(e["device_id"] != assessment.device_id or e["channel"] != assessment.channel or e["code"] != code
               for code, e in existing.items()):
            raise ValueError("EVENT_CONTEXT_MISMATCH")
        ref = assessment.observation
        decisions = {f.code: f for f in assessment.findings}
        updates, inserts, links, resolved_codes = {}, [], [], []
        for code in sorted(existing.keys() | decisions.keys()):
            finding = decisions.get(code)
            payload = deepcopy(existing.get(code))
            visual = assessment.channel == "visual" and code in VISUAL_RULES
            # A later missing-channel report is a watermark even though it cannot replace current.
            interrupted_through = (payload or {}).get("visual_recovery", {}).get("interrupted_through")
            if visual and interrupted_through and datetime.fromisoformat(ref.window_end) <= datetime.fromisoformat(interrupted_through):
                continue
            retired_id = None
            if payload and not same_rule(payload, finding):
                payload.update(status="pending", lifecycle_state="INDETERMINATE", state_reason="RULE_CHANGED",
                    assessed_at=assessment.evaluated_at)
                updates[payload["id"]] = payload
                if finding is None or finding.state != FindingState.HIT:
                    continue
                retired_id, payload = payload["id"], None
            if finding is not None and finding.state == FindingState.HIT:
                public = finding.to_dict()
                progress = visual_progress(payload or {}, assessment, finding, session_id=session_id,
                    sequence=sequence, fresh_until=fresh_until) if visual else None
                if payload:
                    payload.update(last_observed_at=ref.observed_at, last_batch_id=ref.batch_id,
                        severity=finding.severity, finding_severity=finding.severity, title=finding.message,
                        rule_identity=public["rule"], publication_status="PROTOTYPE",
                        lifecycle_state="ACTIVE", status="pending", state_reason=None,
                        observation=public["observation"], assessed_at=assessment.evaluated_at)
                    if visual:
                        payload["visual_recovery"] = progress
                    updates[payload["id"]] = payload
                    continue
                event_id = id_factory()
                payload = {"id": event_id, "device": ref.device_id, "device_id": ref.device_id,
                    "type": "水质" if ref.channel == "water" else "视觉信号", "channel": ref.channel,
                    "severity": finding.severity, "finding_severity": finding.severity, "status": "pending",
                    "lifecycle_state": "ACTIVE", "state_reason": None, "publication_status": "PROTOTYPE",
                    "rule_identity": public["rule"], "observation": public["observation"],
                    "title": finding.message, "description": "PROTOTYPE 模拟来源事件，非生产规则或疾病确诊；未实现人工处理工作流。",
                    "source_kind": ref.source_kind, "code": code, "rule_version": finding.rule.version,
                    "occurred_at": ref.observed_at, "received_at": ref.received_at,
                    "last_observed_at": ref.observed_at, "batch_id": ref.batch_id,
                    "last_batch_id": ref.batch_id, "attachments": [], "assessed_at": assessment.evaluated_at}
                if visual:
                    payload["visual_recovery"] = progress
                inserts.append(payload)
                links.append((code, event_id))
                if retired_id:
                    updates[retired_id]["superseded_by"] = event_id
            elif payload:
                risk_changed = other_risk(finding, assessment)
                resolved = finding.state == FindingState.CLEAR and not risk_changed
                recovering = False
                if visual:
                    progress = visual_progress(payload, assessment, finding, session_id=session_id,
                        sequence=sequence, fresh_until=fresh_until)
                    payload["visual_recovery"] = progress
                    resolved = resolved and progress["clear_count"] >= VISUAL_CLEAR_WINDOWS
                    recovering = finding.state == FindingState.CLEAR and progress["clear_count"] > 0 and not resolved
                payload.update(status="closed" if resolved else "pending",
                    lifecycle_state="RESOLVED" if resolved else "ACTIVE" if recovering else "INDETERMINATE",
                    state_reason=None if resolved else "RECOVERY_OBSERVATION" if recovering else
                        "OTHER_RISK_CONDITION_ACTIVE" if risk_changed else finding.reason,
                    assessed_at=assessment.evaluated_at, state_observation=finding.to_dict()["observation"])
                if resolved:
                    payload.update(resolved_at=ref.observed_at, resolution_batch_id=ref.batch_id,
                                   resolution_observation=finding.to_dict()["observation"])
                    resolved_codes.append(code)
                updates[payload["id"]] = payload
        return EventChanges(tuple(updates.values()), tuple(inserts), tuple(links), tuple(resolved_codes))

    @staticmethod
    def legacy_projection(event):
        result = deepcopy(event)
        if "lifecycle_state" not in result:
            result.update(lifecycle_state="INDETERMINATE", state_reason="LEGACY_UNREVIEWED")
        result.setdefault("publication_status", "PROTOTYPE")
        result["severity"] = result.get("finding_severity", result["severity"])
        return result

    def project(self, event, assessment):
        """Only withdraw current certainty; queries cannot persist or resolve episodes."""
        result = self.legacy_projection(event)
        if result.get("lifecycle_state") == "RESOLVED" or result.get("status") == "closed":
            return result
        if (result["device_id"], result["channel"]) != (assessment.device_id, assessment.channel):
            raise ValueError("EVENT_CONTEXT_MISMATCH")
        finding = next((f for f in assessment.findings if f.code == result["code"]), None)
        match = same_rule(result, finding)
        progress = result.get("visual_recovery", {})
        recovering = (result.get("channel") == "visual" and result.get("code") in VISUAL_RULES
            and match and finding.state == FindingState.CLEAR and 0 < progress.get("clear_count", 0) < VISUAL_CLEAR_WINDOWS
            and assessment.data_quality.quality == "valid" and assessment.data_quality.freshness == "fresh"
            and assessment.data_quality.connectivity == "online" and assessment.observation is not None
            and progress.get("batch_id") == assessment.observation.batch_id)
        if result.get("superseded_by") or not match or finding.state != FindingState.HIT and not recovering:
            result.update(lifecycle_state="INDETERMINATE", status="pending",
                state_reason="RULE_CHANGED" if finding and not match else
                "OTHER_RISK_CONDITION_ACTIVE" if other_risk(finding, assessment) else
                "STALE_OR_OFFLINE" if result.get("code") in VISUAL_RULES and (
                    assessment.data_quality.freshness != "fresh" or assessment.data_quality.connectivity != "online") else
                result.get("state_reason") or "CURRENT_EVIDENCE_UNAVAILABLE")
            if result.get("channel") == "visual" and result.get("code") in VISUAL_RULES:
                interrupt_visual(result, result["state_reason"], assessment.evaluated_at)
        result["evaluated_at"] = assessment.evaluated_at
        return result
