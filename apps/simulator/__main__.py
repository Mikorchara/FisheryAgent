"""Continuous producer CLI; dry-run advances time without any network request."""

import argparse
from datetime import datetime, timezone
import os
import time

from .generator import Simulator
from .scenarios import SCENARIOS
from .transport import HttpReporter, ReportError


def run(simulator, reporter, *, interval_s=10, windows=None, switch_to=None, switch_after=0,
        monotonic=time.monotonic, sleep=time.sleep, emit=print):
    start = monotonic()
    index = 0
    slot = 0
    try:
        while windows is None or index < windows:
            if reporter is not None:
                delay = start+(slot+1)*interval_s-monotonic()
                if delay > 0:
                    sleep(delay)
                # Send only the latest complete window after a stall, never backfill.
                latest = max(slot+1, int((monotonic()-start)/interval_s))
                missed = latest-slot-1
                if missed:
                    simulator.skip_windows(missed, interval_s)
                    emit(f"skipped {missed} missed windows / no backfill")
                slot = latest
            if switch_to and simulator.elapsed_s >= switch_after:
                simulator.switch_scenario(switch_to)
                switch_to = None
            batch = simulator.advance(interval_s)
            index += 1
            if batch is None:
                emit(f"window {index}: device offline / no report")
            elif reporter is None:
                emit(f"window {index}: dry-run / water={batch['water'] is not None} / visual={batch['visual'] is not None}")
            else:
                result = reporter.send(batch)
                emit(f"window {index}: {result['status']}")
    finally:
        if reporter is not None:
            reporter.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local monitoring simulator; no AI or NPU inference")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--server", default="http://127.0.0.1:8766")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--sample-period", type=float, default=1)
    parser.add_argument("--frame-period", type=float, default=.5)
    parser.add_argument("--windows", type=int)
    parser.add_argument("--switch-to", choices=SCENARIOS)
    parser.add_argument("--switch-after", type=float, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if (args.windows is not None and not 1 <= args.windows <= 10000) or not 1 <= args.interval <= 60 or not 0 <= args.switch_after <= 86400:
        parser.error("INVALID_SIMULATOR_BUDGET")
    reporter = None
    try:
        simulator = Simulator(start=datetime.now(timezone.utc), scenario=args.scenario, seed=args.seed,
                              sample_period_s=args.sample_period, frame_period_s=args.frame_period)
        # Validate before any network I/O; discard the detached preflight producer.
        Simulator(start=simulator.start, sample_period_s=args.sample_period, frame_period_s=args.frame_period).advance(args.interval)
        if not args.dry_run:
            reporter = HttpReporter(args.server, os.environ.get("FISHERY_SIM_INGEST_TOKEN", ""))
        run(simulator, reporter, interval_s=args.interval,
            windows=args.windows if args.windows is not None else (3 if args.dry_run else None),
            switch_to=args.switch_to, switch_after=args.switch_after, emit=print)
        return 0
    except KeyboardInterrupt:
        print("Simulator stopped; reporting ended.")
        return 0
    except (ValueError, ReportError) as error:
        print(str(error))  # Only application-defined safe codes, never HTTP bodies or tokens.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
