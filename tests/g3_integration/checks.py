"""Live startup cases and counterexamples replayed from this run's real data."""
import copy
import json
import socket
import time


def gate_checks(task, passed):
    require, Gate = task.amase.require, task.gate.__class__
    directory = task.run / passed['name']
    rows = [json.loads(line) for line in (directory / 'observer.jsonl').read_text(encoding='utf-8').splitlines()]
    java = [json.loads(line) for line in (directory / 'amase.jsonl').read_text(encoding='utf-8').splitlines()]
    results = []
    require(Gate().inspect(rows, java), 'Positive captured initialization failed')
    missing = [r for r in rows if not (r['type'] == 'afrl.cmasi.AirVehicleConfiguration' and r['id'] == '500')]
    require(Gate().inspect(missing, java) is None, 'Missing configuration accepted')
    results.append('missing-configuration-with-both-dynamic-entities')
    for changing_time in (False, True):
        altered = copy.deepcopy(rows)
        positions, times = {}, {}
        for row in altered:
            if row['type'] == 'afrl.cmasi.AirVehicleState':
                entity = row['id']; positions.setdefault(entity, (row['latitude'], row['longitude'])); times.setdefault(entity, row['timeMs'])
                row['latitude'], row['longitude'] = positions[entity]
                if not changing_time: row['timeMs'] = times[entity]
        require(Gate().inspect(altered, java) is None, 'Static state accepted')
        results.append('static-position-' + ('advancing-time' if changing_time else 'static-time'))
    for operation in ('task', 'request', 'request-before-task-initialized', 'duplicate-task', 'duplicate-request'):
        gate = Gate()
        if operation.startswith('duplicate') or operation == 'request-before-task-initialized':
            gate.inspect(rows, java); gate.before_task()
        if operation == 'duplicate-request':
            for row in rows: gate.observe_task(row)
            gate.before_request()
        try:
            (gate.before_task if operation in ('task', 'duplicate-task') else gate.before_request)()
        except RuntimeError:
            results.append('reject-' + operation)
        else:
            raise RuntimeError('Injection gate accepted ' + operation)
    altered = copy.deepcopy(rows)
    next(r for r in altered if r['type'] == 'afrl.cmasi.AirVehicleState')['sourceEntity'] = '900'
    try: Gate().inspect(altered, java)
    except RuntimeError: results.append('reject-non-amase-source')
    else: raise RuntimeError('Injected state source accepted')
    gate = Gate(); gate.inspect(rows, java); gate.before_task()
    gate.observe_task(dict(type='uxas.messages.task.TaskInitialized', taskId='999', sourceEntity='100'))
    require(not gate.task_initialized, 'Wrong task initialized accepted')
    results.append('reject-wrong-task-initialized')
    task.record['gateCounterexamples'] = dict(sourceCase=passed['name'], tests=results, syntheticMutationsOnly=True)


def verify(task):
    failures = []
    positives = []
    for name, mode in [('headless', 'Headless'), ('gui', 'Gui'), ('中文 空格运行', 'Headless')]:
        item = task.case(name, mode)
        if item['status'] != 'passed': failures.append(name + ': ' + item.get('error', 'failed'))
        else: positives.append(item)
    if positives: gate_checks(task, positives[0])
    cases = [('missing-configuration', 'timeout:initial-data'), ('static-state', 'timeout:initial-data'),
             ('early-request', 'AutomationRequest requires TaskInitialized'),
             ('task-initialization-timeout', 'timeout:task-initialized'), ('planning-timeout', 'timeout:planning-response'),
             ('empty-planning-response', 'Planning response has no mission waypoints'),
             ('shutdown-timeout', 'timeout:shutdown')]
    for fault, expected in cases:
        item = task.case(fault, 'Headless', fault=fault)
        verified = item['status'] == 'failed' and expected in item.get('error', '') and item.get('portsReleased')
        if fault != 'shutdown-timeout': verified = verified and item.get('normalExit')
        else:
            verified = verified and len(item['processes']) == 2 and item['processes'][0]['forcedTermination']
            verified = verified and item['processes'][1]['exitCode'] == 0 and not item['processes'][1]['forcedTermination']
            phases = {r['phase']: r['monotonicSeconds'] for r in item['transitions']}
            verified = verified and 30 <= phases['shutdown-finished'] - phases['shutdown-requested'] < 42
        if fault in ('missing-configuration', 'static-state', 'early-request'):
            verified = verified and not any(r['purpose'] in ('task', 'automation-request') for r in item['injections'])
        if fault == 'task-initialization-timeout':
            verified = verified and not any(r['purpose'] == 'automation-request' for r in item['injections'])
        timeouts = [r for r in item['transitions'] if r['phase'].endswith('-timeout')]
        if fault not in ('early-request', 'shutdown-timeout', 'empty-planning-response'):
            verified = verified and len(timeouts) == 1
            if len(timeouts) == 1:
                elapsed = timeouts[0].get('initializationElapsedSeconds') or timeouts[0]['elapsedSeconds']
                verified = verified and 30 <= elapsed < 35
        item['expectedFailureVerified'] = bool(verified)
        # A failed child receipt remains failed; the matrix separately verifies its expected handling.
        task.amase.save(task.run / item['name'] / 'case-result.json', item)
        if not verified: failures.append(fault + ': ' + item.get('error', 'unexpected pass'))
    with socket.socket() as occupied:
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        occupied.bind(('127.0.0.1', task.config['modes']['Headless']['amasePort'])); occupied.listen(1)
        item = task.case('port-conflict', 'Headless')
        verified = item['status'] == 'failed' and not item['processes'] and not item['injections']
        with socket.create_connection(occupied.getsockname(), timeout=1) as client:
            accepted, _ = occupied.accept(); accepted.close()
        item['foreignListenerPreserved'] = True
        item['expectedFailureVerified'] = bool(verified)
        task.amase.save(task.run / item['name'] / 'case-result.json', item)
        if not verified: failures.append('port-conflict did not reject before launching')
    task.amase.check_port(task.config['modes']['Headless']['amasePort'])
    original_deadline = task.operation_deadline
    try:
        task.operation_deadline = time.monotonic() - 1
        try: task.alive()
        except RuntimeError as error:
            if str(error) != 'timeout:whole-run': raise
        else: raise RuntimeError('Whole-run budget did not reject expired operation')
        task.record['wholeRunBudgetCheck'] = dict(automaticRunLimitSeconds=2700, operationLimitSeconds=2650,
                                                cleanupReserveSeconds=50, expiredOperationRejected=True)
    finally:
        task.operation_deadline = original_deadline
    if failures: raise RuntimeError('Acceptance cases failed: ' + '; '.join(failures))
