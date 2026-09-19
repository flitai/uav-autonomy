"""Independent observer gateway worker. It never controls a backend process."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time

from .codec import load_schema, require
from .journal import EventStore, Journal
from .publication import Publication
from .state import State
from .transport import TcpCapture
from .windows import process_identity


class Gateway:
    def __init__(self, root, manifest_path, manifest_sha256, output, config):
        self.root, self.manifest_path, self.output = Path(root), Path(manifest_path), Path(output)
        raw = self.manifest_path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == manifest_sha256.lower(), 'Gateway manifest hash differs')
        self.manifest, self.manifest_sha256 = json.loads(raw), manifest_sha256.lower()
        require(self.manifest['schema_version'] == 1, 'Unsupported runtime manifest')
        require(0 < len(self.manifest['entity_ids']) <= 20 and len(set(self.manifest['entity_ids'])) == len(self.manifest['entity_ids']),
                'Invalid configured entity list')
        self.config = config
        require(config['host'] == '127.0.0.1' and config['readOnly'] is True, 'Gateway must be local and read-only')
        require(0 < config['clientQueueMessages'] <= 256 and 0 < config['clientQueueBytes'] <= 8388608, 'Invalid client limits')
        self.publication = Publication(State(self.manifest['run_id'], self.manifest['entity_ids']),
                                       config['clientQueueMessages'], config['clientQueueBytes'])
        self.output.mkdir(parents=True, exist_ok=False)
        self.stop_requested = threading.Event()
        self.thread = threading.Thread(target=self.work, name='g4-gateway', daemon=True)
        self.captures, self.error, self.status = {}, None, 'initializing'
        self.journal, self.store = None, None
        self.started = time.monotonic()
        self.records = 0

    def check_identity(self):
        require(hashlib.sha256(self.manifest_path.read_bytes()).hexdigest() == self.manifest_sha256, 'Runtime identity changed')
        for expected in self.manifest['processes']:
            require(process_identity(expected['pid']) == expected, 'Backend process identity changed')

    def start(self):
        self.thread.start()

    def health(self):
        with self.publication.lock:
            state = self.publication.state
            return {**self.publication.header('health'), 'status': self.status, 'ready': self.publication.ready,
                    'received_at': datetime.now(timezone.utc).isoformat(),
                    'connections': {name: {'connected': not capture.disconnected and capture.error is None,
                                           'frames': str(capture.frames), 'error': capture.error}
                                    for name, capture in list(self.captures.items())},
                    'initialization': {'expected_entity_ids': self.manifest['entity_ids'],
                                       'configured_entity_ids': sorted(k for k, v in state.data['entities'].items() if 'configuration' in v),
                                       'dynamic_entity_ids': sorted(k for k, v in state.data['entities'].items() if 'state' in v)},
                    'recording': self.store is not None and self.error is None,
                    'recovery': {'active': self.status == 'recovering', 'cursor': list(map(str, state.cursor))},
                    'error': self.error, 'metrics': self.publication.metrics()}

    def set_status(self, status, error=None):
        with self.publication.lock:
            self.status, self.error = status, error
            if status != 'live':
                self.publication.suspend(error or status)
        with (self.output / 'health-events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(self.health(), ensure_ascii=False) + '\n')

    def ready(self):
        state = self.publication.state
        initialized = bool(state.data['simulation']) and all(
            'configuration' in state.data['entities'].get(identifier, {}) and 'state' in state.data['entities'].get(identifier, {})
            for identifier in self.manifest['entity_ids'])
        if not initialized:
            return False
        return all(c.last_received is not None and time.monotonic() - c.last_received <= self.config['staleAfterSeconds']
                   for c in self.captures.values())

    def work(self):
        try:
            self.check_identity()
            schema = load_schema(self.root)
            for channel in ('amase', 'uxas'):
                self.captures[channel] = TcpCapture('127.0.0.1', self.manifest['ports'][channel], channel,
                                                     self.output / channel, schema, self.manifest['entity_ids'])
            binding = {'run_id': self.manifest['run_id'], 'log_directory': self.manifest['log_directory'],
                       'runtime_manifest_sha256': self.manifest_sha256, 'processes': self.manifest['processes']}
            binding_path = self.output / 'journal-binding.json'
            binding_path.write_text(json.dumps(binding, indent=2), encoding='utf-8')
            self.journal = Journal(binding_path, self.manifest['run_id'], schema, self.manifest['entity_ids'])
            self.store = EventStore(self.output / 'normalized-events.db3', binding)
            while not self.stop_requested.is_set():
                self.check_identity()
                for capture in self.captures.values():
                    require(capture.error is None and not capture.disconnected, 'Observation connection failed: ' + capture.channel)
                boundary = self.journal.boundary()
                for event in self.journal.read(boundary, self.publication.state.cursor):
                    if self.stop_requested.is_set():
                        break
                    self.store.append(event)
                    self.publication.apply(event)
                    self.records += 1
                if self.ready():
                    if not self.publication.ready:
                        with self.publication.lock:
                            self.publication.ready = True
                        self.set_status('live')
                elif self.publication.ready:
                    self.set_status('degraded', 'Source data is stale')
                self.stop_requested.wait(self.config['journalPollSeconds'])
        except Exception as error:
            self.set_status('degraded', str(error))
        finally:
            for capture in self.captures.values():
                capture.close()
            if self.store is not None:
                self.store.close(); self.store = None
            self.publication.suspend('gateway stopped')
            record = {'status': 'passed' if self.error is None else 'failed', 'error': self.error,
                      'run_id': self.manifest['run_id'], 'stream_id': self.publication.stream_id,
                      'record_count': str(self.records), 'state_sha256': self.publication.state.fingerprint(),
                      'cursor': list(map(str, self.publication.state.cursor)), 'sent_business_frames': 0,
                      'sources': {name: capture.summary() for name, capture in self.captures.items()},
                      'metrics': self.publication.metrics()}
            (self.output / 'result.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
            (self.output / 'final-state.json').write_text(json.dumps(self.publication.state.snapshot(), indent=2), encoding='utf-8')

    def stop(self):
        self.stop_requested.set()
        self.thread.join(self.config['shutdownTimeoutSeconds'])
        require(not self.thread.is_alive(), 'Gateway observer did not stop')
