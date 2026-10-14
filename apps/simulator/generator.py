"""Fast deterministic clock advancement; water samples and frames share one timeline."""

from datetime import timedelta
import math
import random
import uuid

from apps.monitoring.contracts import METRICS, ANOMALIES, BEHAVIORS, identifier
from .scenarios import SCENARIOS, at_time


class WaterQualityGenerator:
    def __init__(self, seed, sample_period_s):
        self.random = random.Random(seed)
        self.sample_period_s = sample_period_s
        self.noise = dict.fromkeys(METRICS, 0.)

    def generate(self, begin, end, phase, state_at):
        duration_s = end-begin
        values = {key: [] for key in METRICS}
        sample_count = round(duration_s/self.sample_period_s)
        for i in range(sample_count):
            current = state_at(begin+(i+1)*self.sample_period_s)
            for key in METRICS:
                amplitude = .04 if key == "ph" else .15
                self.noise[key] = self.noise[key]*.8+self.random.uniform(-amplitude, amplitude)*.2
                if key not in (phase["missing_metric"], phase["invalid_metric"]):
                    values[key].append(round(current[key]+self.noise[key], 3))
        stats = {}
        for key, (_label, unit, _lo, _hi) in METRICS.items():
            samples = values[key]
            stats[key] = {"unit": unit, "mean": round(sum(samples)/len(samples), 3) if samples else None,
                "min": min(samples) if samples else None, "max": max(samples) if samples else None,
                "latest": samples[-1] if samples else None, "valid_samples": len(samples),
                "invalid_samples": sample_count if phase["invalid_metric"] == key else 0}
        return {"aggregation": "window_mean", "sample_count": sample_count, "metrics": stats}


class VisualDetectionGenerator:
    def __init__(self, seed, frame_period_s):
        self.random = random.Random(seed)
        self.frame_period_s = frame_period_s

    def generate(self, begin, end, phase, state_at):
        duration_s = end-begin
        count = round(duration_s/self.frame_period_s)
        anomalies = dict.fromkeys(ANOMALIES, 0)
        behaviors = dict.fromkeys(BEHAVIORS, 0)
        counts, lengths = [], []
        for i in range(count):
            current = state_at(begin+(i+1)*self.frame_period_s)
            for key, rate in zip(ANOMALIES, ("lesion_rate", "surface_rate", "death_rate")):
                anomalies[key] += int(self.random.random() < current[rate])
            r = self.random.random()
            cumulative = 0
            selected = "normal_activity"
            for key in ("feeding_anomaly", "reduced_activity", "feeding", "unknown"):
                cumulative += current["unknown_behavior" if key == "unknown" else key]
                if r < cumulative:
                    selected = key
                    break
            behaviors[selected] += 1
            counts.append(8+self.random.randint(-2, 2))
            if phase["calibrated"]:
                lengths.append(20+self.random.uniform(-1, 1))
        return {"aggregation": "window_summary", "frames_processed": count,
            "anomaly_counts": anomalies, "behavior_ratios": {k: v/count for k, v in behaviors.items()},
            "length": {"average_length_cm": round(sum(lengths)/len(lengths), 3) if lengths else None,
                "length_sample_count": len(lengths), "calibration": "simulated" if lengths else "uncalibrated",
                "calibration_id": "synthetic-calibration-v1" if lengths else None},
            "visible_fish_count": sum(counts)/count, "model_version": "synthetic-visual-v1"}


class Simulator:
    def __init__(self, *, start, scenario="normal", seed=42, device_id="sim-pond-1", session_id=None,
                 sample_period_s=1, frame_period_s=.5):
        if start.tzinfo is None or scenario not in SCENARIOS:
            raise ValueError("INVALID_SIMULATOR_CONFIG")
        if type(seed) is not int:
            raise ValueError("INVALID_SIMULATOR_SEED")
        for period in (sample_period_s, frame_period_s):
            if type(period) not in (int, float) or not math.isfinite(period) or not .1 <= period <= 10:
                raise ValueError("INVALID_SAMPLING_PERIOD")
        identifier(device_id)
        self.session_id = session_id or uuid.uuid4().hex
        identifier(self.session_id)
        self.start, self.scenario, self.device_id = start, scenario, device_id
        self.water_generator = WaterQualityGenerator(seed, sample_period_s)
        self.visual_generator = VisualDetectionGenerator(seed+1, frame_period_s)
        self.sample_period_s, self.frame_period_s = sample_period_s, frame_period_s
        self.elapsed_s, self.sequence = 0., 0

    def switch_scenario(self, scenario):
        if scenario not in SCENARIOS:
            raise ValueError("UNKNOWN_SCENARIO")
        # A scenario change never resets time, RNG or batch sequence.
        self.scenario = scenario

    def advance(self, duration_s=10):
        if type(duration_s) not in (int, float) or not math.isfinite(duration_s) or not 1 <= duration_s <= 60:
            raise ValueError("INVALID_REPORT_PERIOD")
        # Align periods so every window has a complete, deterministic set of samples.
        for period in (self.sample_period_s, self.frame_period_s):
            if abs(duration_s/period-round(duration_s/period)) > .00001:
                raise ValueError("REPORT_PERIOD_NOT_ALIGNED")
        begin, end = self.elapsed_s, self.elapsed_s+duration_s
        phase = at_time(SCENARIOS[self.scenario], end)
        sequence = self.sequence
        self.elapsed_s, self.sequence = end, sequence+1
        if not phase["online"]:
            return None
        water, visual = None, None
        state_at = lambda elapsed: at_time(SCENARIOS[self.scenario], elapsed)
        water = self.water_generator.generate(begin, end, phase, state_at) if phase["water_online"] else None
        visual = self.visual_generator.generate(begin, end, phase, state_at) if phase["visual_online"] else None
        stamp = self.start+timedelta(seconds=end)
        return {"schema_version": 1, "batch_id": uuid.uuid5(uuid.NAMESPACE_URL, f"{self.session_id}:{sequence}").hex,
            "session_id": self.session_id, "sequence": sequence, "device_id": self.device_id,
            "timestamp": stamp.isoformat(), "window": {"start": (self.start+timedelta(seconds=begin)).isoformat(),
                "end": stamp.isoformat(), "duration_s": duration_s}, "water": water, "visual": visual}
