"""Deterministic reproduction of the log reader/writer lock conflict."""
from contextlib import closing
import json
import sqlite3


def verify(directory):
    directory.mkdir(parents=True)
    results = []
    for mode in ('delete', 'wal'):
        path = directory / (mode + '.db3')
        with closing(sqlite3.connect(path, timeout=0)) as writer:
            assert writer.execute('PRAGMA journal_mode=' + mode).fetchone()[0] == mode
            writer.execute('CREATE TABLE msg(id INTEGER PRIMARY KEY, xml TEXT)')
            writer.execute("INSERT INTO msg VALUES(1,'first')"); writer.commit()
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as reader:
                reader.execute('BEGIN')
                assert reader.execute('SELECT COUNT(*) FROM msg').fetchone()[0] == 1
                error = None
                try:
                    writer.execute("INSERT INTO msg VALUES(2,'task')"); writer.commit()
                except sqlite3.OperationalError as failure:
                    error = str(failure); writer.rollback()
                assert (error == 'database is locked') if mode == 'delete' else error is None
                assert reader.execute('SELECT COUNT(*) FROM msg').fetchone()[0] == 1
                reader.rollback()
                count = reader.execute('SELECT COUNT(*) FROM msg').fetchone()[0]
                assert count == (1 if mode == 'delete' else 2)
                try:
                    reader.execute("INSERT INTO msg VALUES(3,'forbidden')")
                except sqlite3.OperationalError as failure:
                    assert 'readonly' in str(failure)
                else:
                    raise AssertionError('Read-only connection accepted mutation')
                results.append({'mode': mode, 'expectedWriterFailure': error, 'committedRows': count,
                                'readerSnapshotStable': True, 'readOnlyMutationRefused': True})
    result = {'status': 'passed', 'sqliteVersion': sqlite3.sqlite_version, 'cases': results,
              'scope': 'isolated lock reproduction; real C++ writer verified separately'}
    (directory / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
