"""Snapshot/subscription boundary and bounded, independent client mailboxes."""
from collections import deque
from copy import deepcopy
import json
import threading
import uuid

from .codec import require


class Mailbox:
    def __init__(self, message_limit, byte_limit):
        self.message_limit, self.byte_limit = message_limit, byte_limit
        self.items, self.bytes = deque(), 0
        self.peak_messages, self.peak_bytes = 0, 0
        self.closed, self.reason = False, None
        self.condition = threading.Condition()

    def put(self, message):
        size = len(message.encode('utf-8'))
        with self.condition:
            if self.closed:
                return
            if len(self.items) >= self.message_limit or self.bytes + size > self.byte_limit:
                self.close('resynchronize: client queue limit exceeded')
                return
            self.items.append((message, size)); self.bytes += size
            self.peak_messages = max(self.peak_messages, len(self.items))
            self.peak_bytes = max(self.peak_bytes, self.bytes)
            self.condition.notify()

    def get(self, timeout=0.5):
        with self.condition:
            if not self.items and not self.closed:
                self.condition.wait(timeout)
            if self.closed:
                return None
            if self.items:
                message, size = self.items.popleft(); self.bytes -= size
                return message
            return None

    def close(self, reason='closed'):
        with self.condition:
            self.closed, self.reason = True, reason
            self.items.clear(); self.bytes = 0
            self.condition.notify_all()


class Publication:
    def __init__(self, state, message_limit=256, byte_limit=8388608, client_limit=16):
        self.state = state
        self.lock = threading.RLock()
        self.stream_id = str(uuid.uuid4())
        self.clients = set()
        self.message_limit, self.byte_limit, self.client_limit = message_limit, byte_limit, client_limit
        self.ready = False
        self.delta_count, self.client_queue_peak, self.client_bytes_peak, self.slow_clients = 0, 0, 0, 0

    def header(self, kind, source_time=None):
        return {'schema_version': 1, 'run_id': self.state.run_id, 'stream_id': self.stream_id,
                'sequence': str(self.state.sequence), 'kind': kind,
                'source_time_ms': source_time if source_time is not None else self.state.data['simulation'].get('simulation_time_ms')}

    def snapshot(self):
        with self.lock:
            require(self.ready, 'Complete snapshot is not available')
            return {**self.header('snapshot'), 'state': self.state.snapshot()}

    def subscribe(self):
        # Both operations share the reducer lock: no lost or repeated interval.
        with self.lock:
            require(len(self.clients) < self.client_limit, 'Client limit exceeded')
            snapshot = self.snapshot()
            mailbox = Mailbox(self.message_limit, self.byte_limit)
            self.clients.add(mailbox)
            return snapshot, mailbox

    def unsubscribe(self, mailbox):
        with self.lock:
            self.clients.discard(mailbox)
            mailbox.close()

    def apply(self, event):
        with self.lock:
            changes = self.state.apply(event)
            if not changes or not self.ready:
                return
            packet = {**self.header('delta', event['source_time_ms']), 'changes': changes}
            message = json.dumps(packet, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            self.delta_count += 1
            for client in list(self.clients):
                client.put(message)
                self.client_queue_peak = max(self.client_queue_peak, client.peak_messages)
                self.client_bytes_peak = max(self.client_bytes_peak, client.peak_bytes)
                if client.closed:
                    self.slow_clients += 1
                    self.clients.remove(client)

    def suspend(self, reason):
        with self.lock:
            self.ready = False
            for client in self.clients:
                client.close(reason)
            self.clients.clear()

    def rebuild(self, state):
        with self.lock:
            self.suspend('New snapshot required after recovery')
            self.state = state
            self.stream_id = str(uuid.uuid4())

    def metrics(self):
        with self.lock:
            return {'clients': len(self.clients), 'published_deltas': str(self.delta_count),
                    'client_queue_peak': self.client_queue_peak, 'client_bytes_peak': self.client_bytes_peak,
                    'slow_clients': self.slow_clients}
