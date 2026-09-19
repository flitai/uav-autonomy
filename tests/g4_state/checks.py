"""Independent historical replay, state semantics, and storage failure checks."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import time

from sim_bridge.codec import Decoder, ProtocolError, load_schema, require
from sim_bridge.journal import EventStore, Journal, canonical, digest
from sim_bridge.state import State


def verify(root, directory):
    directory.mkdir(parents=True)
    schema = load_schema(root)
    ids = {'400', '500'}
    source = root / 'out/runs/g3-t07-test-20260919-173116-474/headless/uxas/datawork/SavedMessages'
    binding = {'run_id': 'g4-state-history', 'log_directory': str(source)}
    binding_path = directory / 'binding.json'
    binding_path.write_text(canonical(binding), encoding='utf-8')
    reader = Journal(binding_path, binding['run_id'], schema, ids)
    boundary = reader.boundary()
    store = EventStore(directory / 'events.db3', binding)
    state = State(binding['run_id'], ids)
    checks, samples, count = [], {}, 0
    began = time.monotonic()
    for event in reader.read(boundary):
        require(store.append(event), 'Unexpected duplicate record')
        state.apply(event)
        samples[event['message']['type'].split('.')[-1]] = event
        count += 1
    require(count == 6834 and state.data['tasks']['1000']['backend_completed'], 'Historical completion missing')
    require(state.data['tasks']['1000']['completed_entity_ids'] == ['400'], 'Completion identity differs')
    require(set(state.data['entities']) == ids and set(state.data['routes']) == {'400'}, 'State entity/route association differs')
    checks.append('real-history-completion-and-identities')
    first_hash, first_state = state.fingerprint(), state.snapshot()
    rebuilt = State(binding['run_id'], ids)
    for event in store.records():
        rebuilt.apply(event)
        require(not store.append(event), 'Duplicate durable record inserted')
        require(rebuilt.apply(event) == [], 'Duplicate reducer event emitted')
    require(rebuilt.snapshot() == first_state, 'Normalized replay differs')
    fresh = State(binding['run_id'], ids)
    for event in Journal(binding_path, binding['run_id'], schema, ids).read(boundary):
        fresh.apply(event)
    require(fresh.fingerprint() == first_hash, 'Independent source reread differs')
    checks += ['deterministic-record-rebuild', 'deterministic-source-rebuild', 'duplicate-event-idempotence']

    def rejects(name, function):
        try:
            function()
        except (ValueError, sqlite3.Error, OSError, KeyError):
            checks.append(name)
        else:
            raise AssertionError('Expected rejection: ' + name)

    modified = deepcopy(event); modified['source_time_ms'] = '999'
    rejects('changed-committed-event', lambda: store.append(modified))
    modified = deepcopy(event); modified['run_id'] = 'other'
    rejects('different-run-state', lambda: state.apply(modified))
    rejects('different-run-store', lambda: store.append(modified))
    rejects('different-run-binding', lambda: Journal(binding_path, 'other', schema, ids))
    modified = deepcopy(event); modified['event_id']['row_id'] = str(count + 2)
    rejects('out-of-order-gap', lambda: state.apply(modified))
    rejects('truncated-behind-cursor', lambda: list(reader.read(boundary, (1, count + 1))))
    # Exercise semantic transitions with generated objects; these are fixtures,
    # not evidence of point/area task execution (G4-T07).
    simulation = State('fixtures', ids)
    number = 0

    def feed(obj=None, sample=None, entity='100', service='1'):
        nonlocal number
        number += 1
        if sample is not None:
            record = deepcopy(sample)
        else:
            from lmcp.LMCPFactory import packMessage
            descriptor = obj.FULL_LMCP_TYPE_NAME
            body = (descriptor + '$lmcp|' + descriptor + '||' + entity + '|' + service + '$').encode() + packMessage(obj, True)
            record = {'message': Decoder(schema).decode({'body': body}).metadata(), 'source_time_ms': '0'}
        record.update(run_id='fixtures', event_id={'shard': '1', 'row_id': str(number)})
        simulation.apply(record)
        return record

    for task_kind, task_id in [('PointSearchTask', 21), ('LineSearchTask', 22), ('AreaSearchTask', 23)]:
        obj = schema.factory.createObjectByName('CMASI', task_kind); obj.TaskID = task_id; obj.EligibleEntities = [400]
        if task_kind == 'PointSearchTask': obj.SearchLocation = schema.factory.createObjectByName('CMASI', 'Location3D')
        if task_kind == 'AreaSearchTask':
            obj.SearchArea = schema.factory.createObjectByName('CMASI', 'Rectangle')
            obj.SearchArea.CenterPoint = schema.factory.createObjectByName('CMASI', 'Location3D')
            obj.SearchArea.Width, obj.SearchArea.Height = 1000, 500
        feed(obj)
    require({v['kind'] for v in simulation.data['tasks'].values()} == {'point', 'line', 'area'}, 'Task geometry types lost')
    checks.append('three-task-definitions-and-geometry')
    for entity_id in (400, 500):
        command = schema.factory.createObjectByName('CMASI', 'MissionCommand'); command.VehicleID = entity_id; command.CommandID = 7
        feed(command)
    require(set(simulation.data['commands']) == {'400:mission', '500:mission'}, 'Commands crossed entities')
    checks.append('same-command-id-independent-entities')
    latest = deepcopy(samples['AirVehicleState']); latest['message']['fields']['ID'] = '400'
    latest['message']['fields']['CurrentCommand'] = '7'
    feed(sample=latest)
    require(simulation.data['commands']['400:mission']['execution_observed'] and
            not simulation.data['commands']['500:mission']['execution_observed'], 'Execution claim lacks state identity')
    checks.append('received-versus-execution-observed')
    old_snapshot = simulation.snapshot(); old = deepcopy(latest); old['message']['fields']['Time'] = '0'
    feed(sample=old)
    require(simulation.snapshot() == old_snapshot, 'Older entity state overwrote current state')
    checks.append('older-source-time-does-not-overwrite')
    completed = schema.factory.createObjectByName('UXTASK', 'TaskComplete'); completed.TaskID = 21
    completed.EntitiesInvolved = [400]; completed.TimeTaskCompleted = 9007199254740993
    feed(completed)
    require(simulation.data['tasks']['21']['completed_time_ms'] == '9007199254740993', 'Completion time lost precision')
    require('21' in simulation.data['tasks'], 'Completion incorrectly deletes task')
    checks.append('completion-retained-with-int64-time')
    for kind, field, collection, identifier in [('RemoveEntities', 'EntityList', 'entities', 400),
                                               ('RemoveTasks', 'TaskList', 'tasks', 21), ('RemoveZones', 'ZoneList', 'zones', 5)]:
        obj = schema.factory.createObjectByName('CMASI', kind); setattr(obj, field, [identifier]); feed(obj)
        require(str(identifier) not in simulation.data[collection], 'Delete not applied')
    feed(sample=latest); feed(completed)
    require('400' not in simulation.data['entities'] and '21' not in simulation.data['tasks'] and
            '400:mission' not in simulation.data['commands'], 'Deleted object resurrected')
    require(old_snapshot['entities']['400']['simulation_time_ms'] == latest['message']['fields']['Time'], 'Snapshot alias mutated')
    checks += ['explicit-deletion-and-dependent-cleanup', 'no-stale-resurrection', 'snapshot-copy-isolation']
    bad_command = schema.factory.createObjectByName('CMASI', 'MissionCommand'); bad_command.VehicleID = 400
    bad_waypoint = schema.factory.createObjectByName('CMASI', 'Waypoint'); bad_waypoint.Latitude = 91
    bad_command.WaypointList = [bad_waypoint]
    rejects('invalid-derived-waypoint-location', lambda: feed(bad_command))
    wrong_completion = deepcopy(samples['TaskComplete'])
    wrong_completion['message']['fields']['EntitiesInvolved'] = ['999']
    wrong_completion.update(event_id={'shard': '1', 'row_id': str(count + 1)})
    rejects('foreign-completion-entity', lambda: state.apply(wrong_completion))
    # Only a private SQLite copy is mutated for corruption / truncation tests.
    isolated = directory / 'isolated'; isolated.mkdir()
    database = isolated / boundary[0]['file']; shutil.copy2(source / database.name, database)
    local_binding = {**binding, 'log_directory': str(isolated)}
    local_path = directory / 'isolated-binding.json'; local_path.write_text(canonical(local_binding))
    local = Journal(local_path, binding['run_id'], schema, ids); local_boundary = local.boundary()
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute('SELECT * FROM msg WHERE descriptor=? LIMIT 1', ('afrl.cmasi.AirVehicleState',)).fetchone()
        bad = list(row); bad[-1] = row[-1].replace('<Time>0</Time>', '')
        rejects('missing-required-xml-field', lambda: local.decode(bad, 1))
        bad[-1] = row[-1].replace('<AltitudeType>MSL</AltitudeType>', '<AltitudeType>Invalid</AltitudeType>')
        rejects('invalid-enum-not-defaulted', lambda: local.decode(bad, 1))
        bad[-1] = row[-1].replace('<Latitude>45.317100000000003</Latitude>', '<Latitude>nan</Latitude>')
        rejects('invalid-journal-number', lambda: local.decode(bad, 1))
        bad[-1] = '<!DOCTYPE x [<!ENTITY x "x">]>' + row[-1]
        rejects('xml-entity-declaration', lambda: local.decode(bad, 1))
        connection.execute('DELETE FROM msg WHERE id=2')
        connection.commit()
    rejects('missing-journal-row', lambda: list(local.read(local_boundary)))
    database.rename(database.with_suffix('.removed'))
    rejects('missing-shard', local.boundary)
    database.write_bytes(b'not a database')
    rejects('corrupt-or-replaced-shard', local.boundary)
    local_path.write_text(canonical({**local_binding, 'run_id': 'changed'}))
    rejects('binding-changed', lambda: local.connect(database))
    rotation = directory / 'rotation'; rotation.mkdir()
    rotation_binding = {**binding, 'log_directory': str(rotation)}
    rotation_path = directory / 'rotation-binding.json'; rotation_path.write_text(canonical(rotation_binding))
    with closing(sqlite3.connect((source / boundary[0]['file']).as_uri() + '?mode=ro', uri=True)) as connection:
        rows = connection.execute('SELECT * FROM msg WHERE id<=4 ORDER BY id').fetchall()
        sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='msg'").fetchone()[0]
    for shard in (1, 2):
        with closing(sqlite3.connect(rotation / ('messageLog_' + str(shard) + '_0.db3'))) as connection:
            connection.execute(sql)
            connection.executemany('INSERT INTO msg VALUES(?,?,?,?,?,?,?)',
                                   [(n + 1, *row[1:]) for n, row in enumerate(rows[(shard - 1) * 2:shard * 2])])
            connection.commit()
    rotating = Journal(rotation_path, binding['run_id'], schema, ids); rotation_boundary = rotating.boundary()
    require([e['event_id'] for e in rotating.read(rotation_boundary, (1, 2))] ==
            [{'shard': '2', 'row_id': '1'}, {'shard': '2', 'row_id': '2'}], 'Shard identity / resume order differs')
    checks.append('shard-rollover-and-cursor-order')
    rejects('earlier-shard-behind-cursor', lambda: list(rotating.read(rotation_boundary, (1, 3))))
    with closing(sqlite3.connect(rotation / 'messageLog_1_0.db3')) as connection:
        connection.execute('INSERT INTO msg VALUES(?,?,?,?,?,?,?)', (3, *rows[0][1:])); connection.commit()
    rejects('closed-shard-changed', rotating.boundary)
    store.connection.execute("UPDATE events SET event='{}' WHERE shard=1 AND row_id=1")
    store.connection.commit()
    rejects('normalized-record-corruption', lambda: list(store.records()))
    store.close()
    result = {'status': 'passed', 'historicalRows': count, 'checks': checks, 'stateSHA256': first_hash,
              'seconds': time.monotonic() - began, 'pointAreaExecutionValidated': False}
    (directory / 'checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (directory / 'snapshot.json').write_text(json.dumps(first_state, indent=2), encoding='utf-8')
    return result
