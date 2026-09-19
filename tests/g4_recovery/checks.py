"""Recovery refusal fixtures use isolated copies, never mutate a live journal."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3

from sim_bridge.codec import require
from sim_bridge.journal import EventStore, Journal
from sim_bridge.publication import Publication
from sim_bridge.state import State


def verify(root, directory, schema):
    directory.mkdir()
    source = root / 'out/runs/g3-t07-test-20260919-173116-474/headless/uxas/datawork/SavedMessages'
    checks = []

    def reject(label, action):
        try: action()
        except (ValueError, OSError, sqlite3.Error): checks.append(label)
        else: raise AssertionError('Recovery accepted invalid source: ' + label)

    copy = directory / 'source'; shutil.copytree(source, copy)
    binding = {'run_id': 'isolated-recovery', 'log_directory': str(copy)}
    path = directory / 'binding.json'; path.write_text(json.dumps(binding), encoding='utf-8')
    journal = Journal(path, binding['run_id'], schema, ['400', '500'])
    anchors = journal.anchors()
    binding['journal_anchors'] = anchors; path.write_text(json.dumps(binding), encoding='utf-8')
    store = EventStore(directory / 'events.db3', binding)
    initial = State(binding['run_id'], ['400', '500'])
    for event in Journal(path, binding['run_id'], schema, ['400', '500']).read(anchors):
        store.append(event); initial.apply(event)
    require(store.boundaries() == {1: 6834}, 'Persistent high-water boundary differs')
    store.close()
    store = EventStore(directory / 'events.db3', binding)
    replay = State(binding['run_id'], ['400', '500'])
    for event in store.records(): replay.apply(event)
    require(replay.fingerprint() == initial.fingerprint(), 'Process reopen changed state')
    publication = Publication(initial); publication.ready = True
    first, mailbox = publication.subscribe()
    old = publication.stream_id
    publication.rebuild(replay)
    require(publication.stream_id != old and mailbox.closed and not publication.ready, 'Recovery reused old stream boundary')
    reject('snapshot-refused-during-rebuild', publication.snapshot)
    checks += ['durable-reopen-and-completion', 'old-stream-closed-new-identity']
    database = copy / anchors[0]['file']
    with closing(sqlite3.connect(database)) as connection:
        with connection: connection.execute('DELETE FROM msg WHERE id=6834')
    reject('truncation-across-process-restart', lambda: Journal(path, binding['run_id'], schema, ['400','500']).boundary())
    # Restore from the untouched historical file, with a new file identity.
    database.unlink(); shutil.copy2(source / anchors[0]['file'], database)
    reject('same-content-file-replacement-across-restart', lambda: Journal(path, binding['run_id'], schema, ['400','500']).boundary())
    database.write_bytes(b'not a SQLite database')
    binding.pop('journal_anchors'); path.write_text(json.dumps(binding), encoding='utf-8')
    reject('corrupt-journal', lambda: Journal(path, binding['run_id'], schema, ['400','500']).boundary())
    database.unlink()
    reject('missing-journal', lambda: Journal(path, binding['run_id'], schema, ['400','500']).boundary())
    other = deepcopy(binding); other['run_id'] = 'new-backend-run'
    reject('old-ledger-in-new-run', lambda: EventStore(directory / 'events.db3', other))
    with store.connection:
        store.connection.execute("UPDATE events SET event='{}' WHERE shard=1 AND row_id=2")
    reject('corrupt-normalized-record', lambda: list(store.records()))
    store.close()
    result = dict(status='passed', checks=checks, isolatedCopies=True, realTaskExecution=False)
    (directory / 'checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
