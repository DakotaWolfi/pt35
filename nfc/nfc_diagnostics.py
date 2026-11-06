"""Shareable NFC-V diagnostics contain only allowlisted metadata, never RF data."""
from collections import Counter, deque

STAGES = frozenset(('configure', 'inventory', 'system_info', 'extended_info', 'read_block',
                    'geometry', 'coverage', 'shutdown', 'collision_probe'))
RESULTS = frozenset(('ok', 'crc', 'manchester', 'framing', 'fifo', 'timeout', 'tx_timeout', 'size',
                     'collision', 'io', 'unsupported_command', 'unrecognized_command',
                     'unsupported_option', 'block_unavailable', 'block_locked', 'read_protected',
                     'tag_error', 'unknown_geometry', 'partial', 'requested_range_complete',
                     'addressable_memory_complete', 'failed', 'rf_on', 'not_configured', 'interrupted'))
NUMBERS = ('block', 'attempt', 'irq_main', 'irq_timer', 'irq_error', 'fifo_size', 'fifo_status',
           'elapsed_ms', 'identity', 'op', 'rf_bits', 'io2', 'mode', 'stream', 'bitrate', 'tag_error',
           'mask_bits', 'readable', 'requested', 'geometry_blocks', 'geometry_size')
FLAGS = ('fifo_recovered', 'end_recovered')


def safe_event(stage, result, **details):
    """Drop unexpected text or fields, including messages from third-party clients."""
    if stage not in STAGES or result not in RESULTS:
        return None
    event = {'stage': stage, 'result': result}
    for key in NUMBERS:
        value = details.get(key)
        if type(value) is int and 0 <= value <= 65535:
            event[key] = value
    for key in FLAGS:
        if type(details.get(key)) is bool:
            event[key] = details[key]
    return event


class Diagnostics:
    def __init__(self, capacity=1000):
        self.events = deque(maxlen=capacity)
        self.counts = Counter()

    def add(self, stage, result, **details):
        event = safe_event(stage, result, **details)
        if event is not None:
            self.events.append(event)
            self.counts[f'{stage}.{result}'] += 1
            for key in FLAGS:
                if event.get(key):
                    self.counts[f'{stage}.{key}'] += 1

    def export(self):
        return {'format': 'PT35 NFC-V diagnostics 1', 'counts': dict(self.counts),
                'events': list(self.events)}
