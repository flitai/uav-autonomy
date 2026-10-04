"""Read an active, paused G6-B05 segment for a replacement plan.

No function in this module sends a message to AMASE or UxAS.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_execution'))
import core

IDENTITY = ('runId', 'segmentId', 'backendRunId', 'streamId')
VEHICLES = ('400', '500', '600')
TASK_EVENTS = {'uxas.messages.task.TaskActive', 'uxas.messages.task.TaskComplete'}
COMMANDS = {'afrl.cmasi.AutomationResponse', 'afrl.cmasi.MissionCommand',
            'afrl.cmasi.VehicleActionCommand'}


def snapshot(session_file):
    """Return immutable evidence for a started but paused simulation segment."""
    session_file = Path(session_file).resolve()
    session = core.release.load(session_file)
    from sim_bridge.windows import process_identity
    core.need(process_identity(session['amaseProcess']['pid']) == session['amaseProcess'],
              'AMASE process identity changed')
    uxas = core.release.load(session_file.parent / 'uxas/process.json')
    process = process_identity(uxas['pid'])
    core.need(process is not None and uxas['arguments'][0].lower().endswith('uxas.exe'),
              'Active UxAS process is unavailable')
    with urlopen('http://127.0.0.1:8001/api/control/v1/state', timeout=3) as response:
        control = json.load(response)
    core.need(all(control[name] == session[name] for name in IDENTITY[:3]),
              'Active run, segment or backend changed')
    simulation = control.get('simulation')
    core.need(control['started'] is True and simulation is not None and
              simulation['state'] == 2 and int(simulation['simulation_time_ms']) > 0,
              'Pause an executing simulation before replanning')
    sim_ms = int(simulation['simulation_time_ms'])
    rows = core.observer_rows(session_file)
    states = {}
    for row in rows:
        if row['type'] == 'afrl.cmasi.AirVehicleState' and row.get('id') in VEHICLES:
            if int(row['timeMs']) <= sim_ms and (row['id'] not in states or
                    int(row['timeMs']) >= int(states[row['id']]['timeMs'])):
                states[row['id']] = row
    core.need(set(states) == set(VEHICLES), 'Paused aircraft states are incomplete')
    core.need(all(0 <= sim_ms - int(row['timeMs']) <= 2000 for row in states.values()),
              'Aircraft state is stale at pause')
    coverage_path = session_file.parents[1] / 'coverage/live.json'
    core.need(coverage_path.is_file(), 'Coverage snapshot unavailable')
    coverage_bytes = coverage_path.read_bytes()
    coverage = json.loads(coverage_bytes)
    core.need(coverage['runId'] == session['backendRunId'] and
              coverage.get('status') == 'live' and
              0 <= sim_ms - int(coverage['simulationTimeMs']) <= 2000,
              'Coverage snapshot has not reached the pause')
    manifest = core.release.load(session_file.parent / 'gateway-host/manifest.json')
    core.need(manifest['run_id'] == session['backendRunId'],
              'Coverage event ledger belongs to another backend')
    ledger_path = Path(manifest['ledger_path'])
    with sqlite3.connect(ledger_path.resolve().as_uri() + '?mode=ro',
                         uri=True, timeout=.5) as db:
        db.execute('PRAGMA query_only=ON')
        latest = db.execute('SELECT shard,row_id FROM events ORDER BY shard DESC,row_id DESC LIMIT 1').fetchone()
    core.need(latest is not None and tuple(map(int, coverage['cursor'])) == tuple(latest),
              'Coverage collector has not consumed the paused event ledger')
    identity = {key: control[key] for key in IDENTITY}
    return dict(identity=identity, controlSequence=control['controlSequence'],
                simulationTimeMs=str(sim_ms), uxasProcess=process,
                states={vehicle: {key: row[key] for key in
                    ('timeMs', 'rawSHA256', 'xmlBase64', 'latitude', 'longitude')}
                    for vehicle, row in states.items()},
                commandHashes=[row['rawSHA256'] for row in rows if row['type'] in COMMANDS],
                taskEvents=[{key: row.get(key) for key in
                    ('type', 'taskId', 'rawSHA256', 'timeMs')} for row in rows
                    if row['type'] in TASK_EVENTS],
                coverageSHA256=hashlib.sha256(coverage_bytes).hexdigest(),
                coverageCursor=coverage['cursor'],
                coverageSummary=[{key: task[key] for key in
                    ('taskId', 'kind', 'seenCells', 'totalCells', 'observationMilliseconds')}
                    for task in coverage['tasks']])


def settled_snapshot(session_file, seconds=1.2, timeout=10):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            first = snapshot(session_file)
            time.sleep(seconds)
            second = snapshot(session_file)
            unchanged(first, second)
            return second
        except (ValueError, sqlite3.OperationalError) as error:
            last_error = error
            time.sleep(.2)
    raise ValueError('Paused state did not settle: ' + str(last_error))


def unchanged(expected, current):
    core.need(expected['identity'] == current['identity'] and
              expected['controlSequence'] == current['controlSequence'] and
              expected['simulationTimeMs'] == current['simulationTimeMs'] and
              expected['uxasProcess'] == current['uxasProcess'] and
              expected['states'] == current['states'] and
              expected['commandHashes'] == current['commandHashes'] and
              expected['taskEvents'] == current['taskEvents'] and
              expected['coverageSummary'] == current['coverageSummary'],
              'Paused execution changed after replacement planning')
