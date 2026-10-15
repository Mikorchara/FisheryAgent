"""Pure event transitions and read projections. SQL and transaction ownership stay outside."""

from copy import deepcopy
from dataclasses import dataclass
import json
import uuid

from .contracts import ChannelAnalysis, FindingState


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
    def transition(self, existing, assessment, *, id_factory=lambda: uuid.uuid4().hex):
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
                if payload:
                    payload.update(last_observed_at=ref.observed_at, last_batch_id=ref.batch_id,
                        severity=finding.severity, finding_severity=finding.severity, title=finding.message,
                        rule_identity=public["rule"], publication_status="PROTOTYPE",
                        lifecycle_state="ACTIVE", status="pending", state_reason=None,
                        observation=public["observation"], assessed_at=assessment.evaluated_at)
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
                inserts.append(payload)
                links.append((code, event_id))
                if retired_id:
                    updates[retired_id]["superseded_by"] = event_id
            elif payload:
                risk_changed = other_risk(finding, assessment)
                resolved = finding.state == FindingState.CLEAR and not risk_changed
                payload.update(status="closed" if resolved else "pending",
                    lifecycle_state="RESOLVED" if resolved else "INDETERMINATE",
                    state_reason=None if resolved else "OTHER_RISK_CONDITION_ACTIVE" if risk_changed else finding.reason,
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
        if result.get("superseded_by") or not match or finding.state != FindingState.HIT:
            result.update(lifecycle_state="INDETERMINATE", status="pending",
                state_reason="RULE_CHANGED" if finding and not match else
                "OTHER_RISK_CONDITION_ACTIVE" if other_risk(finding, assessment) else
                result.get("state_reason") or "CURRENT_EVIDENCE_UNAVAILABLE")
        result["evaluated_at"] = assessment.evaluated_at
        return result
