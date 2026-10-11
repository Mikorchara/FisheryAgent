"""Read-only P2E preregistration check. This entry cannot execute a Provider."""

import json
from pathlib import Path
import sys

from fishery_ai.assistant_qualification import QualificationManifest
from fishery_ai.qualification_migration import migration_order


def main(argv=None):
    if (sys.argv[1:] if argv is None else argv):
        print(json.dumps({"error_code": "INVALID_QUALIFICATION_ARGUMENTS", "actual_network_requests": 0}))
        return 2
    try:
        root = Path.cwd()
        if not (root / "pyproject.toml").is_file():
            raise ValueError
        folder = root / "scripts/manifests/product-migration"
        index = json.loads((folder / "qualification-plan.json").read_text(encoding="utf-8"))
        expected = {"study": "P2E", "schema_version": 1, "real_provider_results": "NOT_RUN",
                    "max_runs": 30, "max_provider_requests": 60, "max_requests_per_run": 2,
                    "max_output_tokens_per_request": 256, "retry": 0}
        if set(index) != {*expected, "order"} or any(index.get(k) != v for k, v in expected.items()):
            raise ValueError
        order = index["order"]
        if [item["case_id"] for item in order] != list(migration_order()):
            raise ValueError
        plans = []
        for position, item in enumerate(order, 1):
            relative = f"scripts/manifests/product-migration/assistant-{item['case_id']}.json"
            if item["position"] != position or item["manifest"] != relative:
                raise ValueError
            manifest = QualificationManifest.from_json(root / relative)
            plan = manifest.safe_plan()
            if plan["case_id"] != item["case_id"] or plan["plan_sha256"] != item["plan_sha256"]:
                raise ValueError
            plans.append({"position": position, "case_id": item["case_id"], "plan_sha256": item["plan_sha256"]})
        print(json.dumps({"status": "PREPARED", "real_provider_results": "NOT_RUN",
                          "max_runs": 30, "max_provider_requests": 60,
                          "actual_network_requests": 0, "order": plans}, indent=2))
        return 0
    except Exception:
        print(json.dumps({"error_code": "QUALIFICATION_PLAN_INVALID", "actual_network_requests": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
