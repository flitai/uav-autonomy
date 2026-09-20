"""Independent observer with durable semantic recovery, never backend control."""
from collections import OrderedDict, deque
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
from .windows import process_identity, main_connection

CRITICAL = {'AirVehicleConfiguration', 'PointSearchTask', 'LineSearchTask', 'AreaSearchTask',
            'AutomationResponse', 'MissionCommand', 'VehicleActionCommand', 'TaskInitialized',
            'TaskAssignmentSummary', 'TaskActive', 'TaskComplete', 'RemoveEntities', 'RemoveTasks',
            'RemoveZones', 'KeepInZone', 'KeepOutZone', 'OperatingRegion'}


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
        self.records, self.epoch, self.recoveries = 0, 0, 0
        self.history = deque(maxlen=64)
        self.pending, self.committed = OrderedDict(), OrderedDict()
        self.evidence_lock = threading.Lock()
        self.main = self.manifest.get('main_connection')
        self.log_offset, self.log_tail = 0, b''
        self.boundary = []
        self.boundary_observed_at = None

    def check_identity(self):
        require(hashlib.sha256(self.manifest_path.read_bytes()).hexdigest() == self.manifest_sha256, 'Runtime identity changed')
        for expected in self.manifest['processes']:
            require(process_identity(expected['pid']) == expected, 'Backend process identity changed')
        current = main_connection(self.manifest['processes'][1]['pid'],
                                  self.main['remote_port'] if self.main else self.manifest['ports']['amase'])
        if self.main is None:
            self.main = current
        require(current == self.main, 'Main task TCP connection changed; a new whole run is required')
        if self.manifest.get('uxas_stdout'):
            path = Path(self.manifest['uxas_stdout'])
            require(path.is_file() and path.stat().st_size >= self.log_offset, 'Backend diagnostic log missing or truncated')
            with path.open('rb') as stream:
                stream.seek(self.log_offset)
                while block := stream.read(65536):
                    self.log_offset += len(block)
                    combined = self.log_tail + block
                    require(b'ERROR: DatabaseLoggerHelper::' not in combined, 'Backend persistent logging failed')
                    self.log_tail = combined[-256:]

    def start(self):
        self.thread.start()

    def health(self):
        with self.publication.lock:
            state = self.publication.state
            ages = {name: (None if capture.last_received is None else time.monotonic() - capture.last_received)
                    for name, capture in list(self.captures.items())}
            paused = state.data['simulation'].get('state') in (0, 2)
            return {**self.publication.header('health'), 'status': self.status, 'ready': self.publication.ready,
                    'received_at': datetime.now(timezone.utc).isoformat(),
                    'connections': {name: {'connected': not capture.disconnected and capture.error is None,
                                           'frames': str(capture.frames), 'error': capture.error}
                                    for name, capture in list(self.captures.items())},
                    'initialization': {'expected_entity_ids': self.manifest['entity_ids'],
                                       'configured_entity_ids': sorted(k for k, v in state.data['entities'].items() if 'configuration' in v),
                                       'dynamic_entity_ids': sorted(k for k, v in state.data['entities'].items() if 'state' in v)},
                    'recording': self.store is not None and self.error is None,
                    'freshness': {'paused': paused, 'source_ages_seconds': ages,
                                  'stale': not paused and (len(ages) != 2 or any(
                                      age is None or age > self.config['staleAfterSeconds'] for age in ages.values()))},
                    'recovery': {'active': self.status == 'recovering', 'cursor': list(map(str, state.cursor)),
                                 'epoch': str(self.epoch), 'completed': str(self.recoveries),
                                 'boundary': self.boundary, 'wire_gaps_preserved': True},
                    'error': self.error, 'metrics': self.publication.metrics()}

    def set_status(self, status, error=None):
        with self.publication.lock:
            self.status, self.error = status, error
            if status != 'live':
                self.publication.suspend(error or status)
        with (self.output / 'health-events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(self.health(), ensure_ascii=False) + '\n')

    def captured(self, message, row):
        if message.descriptor.split('.')[-1] in CRITICAL:
            checksum = row['rawSHA256']
            with self.evidence_lock:
                if checksum not in self.committed:
                    self.pending.setdefault(checksum, time.monotonic())
                    require(len(self.pending) <= 4096, 'Uncommitted critical-event queue exceeded bound')

    def close_captures(self, reason):
        for capture in self.captures.values():
            capture.close()
            item = {'epoch': str(self.epoch), 'reason': reason, 'source': capture.summary(),
                    'raw_directory': str(capture.folder.relative_to(self.output)), 'wire_bytes_recovered': False}
            self.history.append(item)
            with (self.output / 'connection-events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(item) + '\n')
        self.captures = {}

    def connect(self, schema):
        self.epoch += 1
        try:
            for channel in ('amase', 'uxas'):
                self.captures[channel] = TcpCapture('127.0.0.1', self.manifest['ports'][channel], channel,
                    self.output / ('connection-' + str(self.epoch)) / channel, schema, self.manifest['entity_ids'], self.captured)
        except OSError:
            self.close_captures('connect-failed')
            return False
        return True

    def consume(self, rebuild=False):
        boundary = self.journal.boundary()
        # A rebuild can take longer than the missing-event deadline. Only
        # this captured boundary, not the time replay finishes, proves how
        # far the committed log has actually been inspected.
        boundary_observed_at = time.monotonic()
        available = {int(item['shard']): int(item['row_id']) for item in boundary}
        require(all(available.get(shard, -1) >= count for shard, count in self.store.boundaries().items()),
                'Source journal is behind the durable record')
        if rebuild:
            self.publication.rebuild(State(self.manifest['run_id'], self.manifest['entity_ids']))
        for index, event in enumerate(self.journal.read(boundary, self.publication.state.cursor)):
            if self.stop_requested.is_set():
                return
            if index % 128 == 0:
                self.check_identity()
            self.store.append(event)
            self.publication.apply(event)
            self.records += 1
            message = event['message']
            if message['type'].split('.')[-1] in CRITICAL:
                with self.evidence_lock:
                    checksum = message['rawSHA256']
                    self.pending.pop(checksum, None)
                    self.committed[checksum] = True
                    self.committed.move_to_end(checksum)
                    if len(self.committed) > 4096:
                        self.committed.popitem(last=False)
        self.boundary = boundary
        self.boundary_observed_at = boundary_observed_at

    def critical_evidence_ready(self):
        with self.evidence_lock:
            pending = list(self.pending.items())
        # Recent hashes are bounded in RAM. Replayed configurations and
        # commands may already be durable but have left that cache.
        for checksum, _ in pending:
            if self.store.has_message(checksum):
                with self.evidence_lock:
                    self.pending.pop(checksum, None)
        with self.evidence_lock:
            if not self.pending:
                return True
            oldest = min(self.pending.values())
        require(self.boundary_observed_at is None or self.boundary_observed_at - oldest <= 10,
                'A captured critical event is absent from the committed journal')
        # Remain recovering while the reader catches up; elapsed replay
        # time alone cannot establish that an event is missing.
        return time.monotonic() - oldest <= 10

    def ready(self):
        state = self.publication.state
        initialized = bool(state.data['simulation']) and all(
            identifier in state.deleted['entities'] or
            ('configuration' in state.data['entities'].get(identifier, {}) and 'state' in state.data['entities'].get(identifier, {}))
            for identifier in self.manifest['entity_ids'])
        if not initialized or len(self.captures) != 2 or any(c.disconnected or c.error for c in self.captures.values()):
            return False
        paused = state.data['simulation'].get('state') in (0, 2)
        if not paused and not all(c.last_received is not None and time.monotonic() - c.last_received <= self.config['staleAfterSeconds']
                                  for c in self.captures.values()):
            return False
        if not self.critical_evidence_ready():
            return False
        capture = self.captures['amase']
        with capture.lock:
            samples = list(capture.latest.values())
        for row in samples:
            if row['type'] == 'afrl.cmasi.AirVehicleState' and row['fields']['ID'] not in state.deleted['entities']:
                value = state.data['entities'].get(row['fields']['ID'], {})
                if int(row['fields']['Time']) - int(value.get('simulation_time_ms', '-1')) > 5000:
                    return False
        return True

    def work(self):
        try:
            self.check_identity()
            schema = load_schema(self.root)
            binding = {'run_id': self.manifest['run_id'], 'log_directory': self.manifest['log_directory'],
                       'runtime_manifest_sha256': self.manifest_sha256, 'processes': self.manifest['processes'],
                       'journal_anchors': self.manifest.get('journal_anchors', [])}
            binding_path = self.output / 'journal-binding.json'
            binding_path.write_text(json.dumps(binding, indent=2), encoding='utf-8')
            self.journal = Journal(binding_path, self.manifest['run_id'], schema, self.manifest['entity_ids'])
            store_path = Path(self.manifest.get('ledger_path', self.output / 'normalized-events.db3'))
            require(store_path.parent.is_dir(), 'Durable record parent directory missing')
            self.store = EventStore(store_path, binding)
            self.set_status('recovering')
            self.consume(rebuild=True)
            retry, next_attempt, rebuild, connected_at = 0, 0, False, 0
            while not self.stop_requested.is_set():
                self.check_identity()
                if any(c.error is not None or c.disconnected for c in self.captures.values()):
                    self.set_status('recovering')
                    self.close_captures('observation-interrupted')
                    rebuild = True
                    delays = self.config['reconnectDelaysSeconds']
                    next_attempt = time.monotonic() + delays[min(retry, len(delays) - 1)]
                    retry += 1
                if not self.captures and time.monotonic() >= next_attempt:
                    if self.connect(schema):
                        next_attempt = 0
                        connected_at = time.monotonic()
                    else:
                        delays = self.config['reconnectDelaysSeconds']
                        next_attempt = time.monotonic() + delays[min(retry, len(delays) - 1)]
                        retry += 1
                connected = len(self.captures) == 2 and all(not c.disconnected and not c.error for c in self.captures.values())
                received = connected and all(c.last_received is not None for c in self.captures.values())
                paused_connection = connected and self.publication.state.data['simulation'].get('state') in (0,2) and time.monotonic()-connected_at >= .5
                if rebuild and (received or paused_connection):
                    self.consume(rebuild=True)
                    rebuild = False
                else:
                    self.consume()
                if not rebuild and self.ready():
                    retry = 0
                    if not self.publication.ready:
                        self.check_identity()
                        with self.publication.lock:
                            self.publication.ready = True
                        self.recoveries += 1
                        self.set_status('live')
                elif self.publication.ready:
                    self.set_status('recovering')
                self.stop_requested.wait(self.config['journalPollSeconds'])
        except Exception as error:
            self.set_status('degraded', str(error))
        finally:
            self.close_captures('gateway-stopped')
            if self.store is not None:
                self.store.close(); self.store = None
            self.publication.suspend('gateway stopped')
            record = {'status': 'passed' if self.error is None else 'failed', 'error': self.error,
                      'run_id': self.manifest['run_id'], 'stream_id': self.publication.stream_id,
                      'record_count': str(self.records), 'state_sha256': self.publication.state.fingerprint(),
                      'cursor': list(map(str, self.publication.state.cursor)), 'sent_business_frames': 0,
                      'sources': list(self.history), 'recovery_count': str(self.recoveries), 'epochs': str(self.epoch),
                      'metrics': self.publication.metrics()}
            (self.output / 'result.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
            (self.output / 'final-state.json').write_text(json.dumps(self.publication.state.snapshot(), indent=2), encoding='utf-8')

    def stop(self):
        self.stop_requested.set()
        self.thread.join(self.config['shutdownTimeoutSeconds'])
        require(not self.thread.is_alive(), 'Gateway observer did not stop')
