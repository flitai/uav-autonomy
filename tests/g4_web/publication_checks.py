"""Exercise atomic snapshot boundaries and isolated slow subscribers."""
import json
import threading

from sim_bridge.codec import require
from sim_bridge.publication import Mailbox, Publication
from sim_bridge.state import State


def event(number):
    return {'run_id': 'publication-fixture', 'event_id': {'shard': '1', 'row_id': str(number)}, 'source_time_ms': '0',
            'message': {'type': 'uxas.messages.task.TaskInitialized', 'sourceEntity': '100', 'sourceService': '7',
                        'sourceGroup': '', 'fields': {'TaskID': str(number)}}}


def verify(directory):
    directory.mkdir(parents=True)
    publication = Publication(State('publication-fixture', {'400'}), message_limit=4, byte_limit=4096)
    publication.ready = True
    first, fast = publication.subscribe(); _, slow = publication.subscribe()
    for number in range(1, 21):
        publication.apply(event(number))
        require(json.loads(fast.get(0))['sequence'] == str(number), 'Fast client stalled or missed an event')
    require(slow.closed and publication.slow_clients == 1 and slow.peak_messages == 4, 'Slow client limit not enforced')
    require(not fast.closed and len(publication.state.data['tasks']) == 20, 'Slow client affected shared state')
    byte_limited = Mailbox(256, 20)
    byte_limited.put('a' * 12); byte_limited.put('b' * 12)
    require(byte_limited.closed and byte_limited.peak_bytes == 12, 'Byte limit did not isolate client')
    # Race snapshot registration with real producer mutations. Every event after
    # the selected boundary must be delivered once, regardless of lock timing.
    snapshot_entered, producer_attempted = threading.Event(), threading.Event()
    class ConcurrentSnapshot(State):
        def snapshot(self):
            snapshot_entered.set()
            require(producer_attempted.wait(5), 'Producer did not overlap snapshot generation')
            return super().snapshot()
    atomic = Publication(ConcurrentSnapshot('publication-fixture', {'400'})); atomic.ready = True
    def produce():
        require(snapshot_entered.wait(5), 'Snapshot did not start')
        producer_attempted.set()
        for number in range(1, 201): atomic.apply(event(number))
    producer = threading.Thread(target=produce)
    producer.start(); snapshot, mailbox = atomic.subscribe(); producer.join(5)
    require(not producer.is_alive(), 'Producer blocked')
    sequence = int(snapshot['sequence'])
    require(sequence == 0, 'Producer crossed snapshot registration lock')
    reconstructed = snapshot['state']
    while sequence < 200:
        message = json.loads(mailbox.get(1)); sequence += 1
        require(message['sequence'] == str(sequence), 'Snapshot subscription interval has a gap')
        for change in message['changes']:
            reconstructed[change['collection']][change['id']] = change['value']
    require(reconstructed == atomic.snapshot()['state'], 'Snapshot plus deltas differs from current state')
    atomic.state.sequence = 9007199254740993
    require(atomic.snapshot()['sequence'] == '9007199254740993', 'Large sequence lost precision')
    publication.suspend('rebuild')
    require(fast.closed and not publication.ready, 'Stale stream remained readable')
    result = {'status': 'passed', 'checks': ['slow-client-bounded', 'fast-client-unaffected', 'critical-state-retained',
              'client-byte-limit', 'snapshot-delta-atomic-boundary', 'concurrent-publication', 'large-string-sequence', 'suspend-old-stream'],
              'slowClientQueuePeak': slow.peak_messages, 'productionRecordsUsed': False}
    (directory / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
