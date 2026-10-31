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
        invalid = dict.fromkeys(METRICS, 0)
        sample_count = round(duration_s/self.sample_period_s)
        for i in range(sample_count):
            current = state_at(begin+(i+1)*self.sample_period_s)
            for key in METRICS:
                amplitude = .04 if key == "ph" else .15
                self.noise[key] = self.noise[key]*.8+self.random.uniform(-amplitude, amplitude)*.2
                if not current["online"] or not current["water_online"] or key == current["missing_metric"]:
                    continue
                value = current[key]
                if value is None:
                    continue
                if (key == current["invalid_metric"] or type(value) not in (int, float)
                        or not math.isfinite(value) or not METRICS[key][2] <= value <= METRICS[key][3]):
                    invalid[key] += 1
                else:
                    measured = round(value+self.noise[key], 3)
                    if METRICS[key][2] <= measured <= METRICS[key][3]:
                        values[key].append(measured)
                    else:
                        invalid[key] += 1
        stats = {}
        for key, (_label, unit, _lo, _hi) in METRICS.items():
            samples = values[key]
            stats[key] = {"unit": unit, "mean": round(sum(samples)/len(samples), 3) if samples else None,
                "min": min(samples) if samples else None, "max": max(samples) if samples else None,
                "latest": samples[-1] if samples else None, "valid_samples": len(samples),
                "invalid_samples": invalid[key]}
        return {"aggregation": "window_mean", "sample_count": sample_count, "metrics": stats}


class VisualDetectionGenerator:
    def __init__(self, seed, frame_period_s):
        self.random = random.Random(seed)
        self.frame_period_s = frame_period_s

    def sample_frame(self, current):
        if not current["online"] or not current["visual_online"]:
            return None  # Invalid/unavailable frame, never a zero-fish observation.
        anomalies = tuple(key for key, rate in zip(ANOMALIES,
            ("lesion_rate", "surface_rate", "death_rate")) if self.random.random() < current[rate])
        r, cumulative, selected = self.random.random(), 0, "normal_activity"
        for key in ("feeding_anomaly", "reduced_activity", "feeding", "unknown"):
            cumulative += current["unknown_behavior" if key == "unknown" else key]
            if r < cumulative:
                selected = key
                break
        visible = self.random.randint(0, 10)
        # Some visible fish have no valid length measurement; calibration is per frame.
        lengths = [20+self.random.uniform(-1, 1) for _ in range(self.random.randint(0, visible))] if current["calibrated"] else []
        return {"visible_fish_count": visible, "lengths_cm": lengths,
                "anomalies": anomalies, "behavior": selected}

    def generate(self, begin, end, phase, state_at):
        count = round((end-begin)/self.frame_period_s)
        frames = [self.sample_frame(state_at(begin+(i+1)*self.frame_period_s)) for i in range(count)]
        return summarize_visual_frames(frames)


def summarize_visual_frames(frames):
    """Internal detection records; None marks a failed frame, count=0 valid zero fish.

    Each lengths_cm item is one valid calibrated detection, not a unique fish.
    Frames come from the producer, never from HTTP input.
    """
    valid = [frame for frame in frames if frame is not None]
    counts = [frame["visible_fish_count"] for frame in valid]
    lengths = [value for frame in valid for value in frame["lengths_cm"]]
    length_frames = sum(bool(frame["lengths_cm"]) for frame in valid)
    anomalies = {key: sum(key in frame["anomalies"] for frame in valid) for key in ANOMALIES}
    behaviors = {key: sum(frame["behavior"] == key for frame in valid) for key in BEHAVIORS}
    return {"aggregation": "window_summary", "frames_processed": len(frames), "valid_frames": len(valid),
        "anomaly_counts": anomalies, "behavior_ratios": {k: v/len(valid) if valid else 0 for k, v in behaviors.items()},
        "length": {"average_length_cm": round(math.fsum(lengths)/len(lengths), 3) if lengths else None,
            "length_sample_count": len(lengths), "valid_frame_count": length_frames,
            "calibration": "simulated" if lengths else "uncalibrated",
            "calibration_id": "synthetic-calibration-v1" if lengths else None},
        "visible_fish_count": sum(counts)/len(counts) if counts else None, "model_version": "synthetic-visual-v2"}


class Simulator:
    def __init__(self, *, start, scenario="normal", seed=42, device_id="sim-pond-1", session_id=None,
                 sample_period_s=1, frame_period_s=.5, mode='full'):
        if mode not in ('full','water-only'):raise ValueError('INVALID_SIMULATION_MODE')
        self.mode=mode
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

    def skip_windows(self, count, duration_s):
        """Missed real-time windows produce no samples or reports; retain time gaps."""
        self.elapsed_s += count*duration_s
        self.sequence += count

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
        visual = self.visual_generator.generate(begin, end, phase, state_at) if self.mode=='full' and phase["visual_online"] else None
        if water is None and visual is None:return None
        stamp = self.start+timedelta(seconds=end)
        return {"schema_version": 1, "batch_id": uuid.uuid5(uuid.NAMESPACE_URL, f"{self.session_id}:{sequence}").hex,
            "session_id": self.session_id, "sequence": sequence, "device_id": self.device_id,
            "timestamp": stamp.isoformat(), "window": {"start": (self.start+timedelta(seconds=begin)).isoformat(),
                "end": stamp.isoformat(), "duration_s": duration_s}, "water": water, "visual": visual}
