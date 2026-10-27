"""Offline-only spans. No arguments, return values, identities or text are retained."""
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps
import inspect
import sys
import threading
import time
from unittest.mock import patch


class Observer:
    def __init__(self):
        self.events = []
        self.enabled = True
        self.active = None
        self.lock = threading.RLock()
        self.local = threading.local()
        self.next_id = 0

    @contextmanager
    def span(self, label):
        if not self.enabled or self.active is None:
            yield
            return
        with self.lock:
            self.next_id += 1
            identifier = self.next_id
            sample = self.active
        stack = getattr(self.local, 'stack', None)
        if stack is None:
            stack = self.local.stack = []
        parent = stack[-1] if stack else None
        start = time.perf_counter_ns()
        stack.append(identifier)
        try:
            yield
        finally:
            end = time.perf_counter_ns()
            stack.pop()
            with self.lock:
                self.events.append({'sample': sample, 'label': label, 'id': identifier,
                    'parent': parent, 'thread': threading.current_thread().name,
                    'start_ns': start, 'end_ns': end})

    def wrap(self, label, function):
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def async_call(*args, **kwargs):
                with self.span(label):
                    return await function(*args, **kwargs)
            return async_call
        @wraps(function)
        def call(*args, **kwargs):
            with self.span(label):
                return function(*args, **kwargs)
        return call

    def method(self, stack, owner, name, label):
        stack.enter_context(patch.object(owner, name, self.wrap(label, getattr(owner, name))))

    def aliases(self, stack, function, label):
        """Instrument every already-imported alias, without replacing its behavior."""
        wrapped = self.wrap(label, function)
        for module in tuple(sys.modules.values()):
            if not module or not getattr(module, '__name__', '').startswith('apps.'):
                continue
            for name, value in tuple(vars(module).items()):
                if value is function:
                    stack.enter_context(patch.object(module, name, wrapped))

    def summary(self, sample):
        events = [e for e in self.events if e['sample'] == sample]
        children = defaultdict(int)
        totals = defaultdict(lambda: {'calls': 0, 'inclusive_ms': 0.0, 'exclusive_ms': 0.0})
        for e in events:
            if e['parent'] is not None:
                children[e['parent']] += e['end_ns'] - e['start_ns']
        for e in events:
            duration = e['end_ns'] - e['start_ns']
            item = totals[e['label']]
            item['calls'] += 1
            item['inclusive_ms'] += duration / 1e6
            item['exclusive_ms'] += max(0, duration - children[e['id']]) / 1e6
        return {key: {k: round(v, 6) if isinstance(v, float) else v for k, v in value.items()}
                for key, value in sorted(totals.items())}


def statistics(values, *, stable_threshold=30):
    """Nearest-rank P95 only when at least 30 successful observations exist."""
    import math
    import statistics as stats
    if not values:
        return {'n': 0, 'median': None, 'p95': None, 'min': None, 'max': None}
    values = sorted(values)
    return {'n': len(values), 'median': stats.median(values),
            'p95': values[math.ceil(.95 * len(values))-1] if len(values) >= stable_threshold else None,
            'min': values[0], 'max': values[-1]}
