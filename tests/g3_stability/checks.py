"""Native child runs and isolated production-validator failures for G3-T06."""
import copy
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time


def isolated_sources(task):
    package = task.amase  # AMASE and UxAS retain their own production validators.
    # Resolve through the runtime module's already loaded qualified release implementation.
    import importlib.util
    spec = importlib.util.spec_from_file_location('stability_package', task.root / 'scripts/uxas_release/package.py')
    release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)
    base = task.run / 'isolated-sources'; base.mkdir()
    results = []

    def reject(name, action, diagnostic):
        folder = base / name; folder.mkdir(exist_ok=True)
        result = dict(name=name, status='running', applicationLaunched=False)
        try: action(folder)
        except (RuntimeError, OSError) as error:
            result.update(status='failed', error=str(error))
        else: result.update(status='passed')
        package.save(folder / 'result.json', result)
        verified = result['status'] == 'failed' and diagnostic.lower() in result.get('error', '').lower()
        results.append(dict(name=name, expectedRejectionVerified=verified, childStatus=result['status'],
                            resultSHA256=package.sha(folder / 'result.json')))
        package.require(verified, name + ': ' + result.get('error', 'Invalid source was accepted'))

    # Use the same accepted library record against a missing and a corrupt isolated copy.
    jar_record = dict(path='OpenAMASE.jar', sha256=package.sha(task.folder / 'OpenAMASE.jar'))
    reject('missing-amase', lambda folder: package.verify_records(folder, [jar_record]), 'missing')
    def corrupt_jar(folder):
        shutil.copyfile(task.folder / 'OpenAMASE.jar', folder / 'OpenAMASE.jar')
        with (folder / 'OpenAMASE.jar').open('ab') as stream: stream.write(b'T06 isolated corruption')
        package.verify_records(folder, [jar_record])
    reject('corrupt-amase', corrupt_jar, 'hash')
    for kind in ('missing-uxas', 'corrupt-uxas', 'mixed-uxas-provenance'):
        def check(folder, kind=kind):
            target = folder / 'package'; shutil.copytree(task.uxas, target)
            provenance = copy.deepcopy(task.baseline['provenance'])
            if kind == 'missing-uxas': (target / 'uxas.exe').unlink()
            elif kind == 'corrupt-uxas':
                with (target / 'uxas.exe').open('ab') as stream: stream.write(b'T06 isolated corruption')
            else: provenance['buildRunId'] = 'unrelated-build'
            release.check(target, package.sha(task.uxas / 'build-info.json'), provenance)
        reject(kind, check, 'missing' if kind.startswith('missing') else 'hash' if kind.startswith('corrupt') else 'identity')
    candidate = release.candidate_args(task.root, task.baseline['provenance']).candidate
    lmcp = Path(release.load(candidate / 'build-info.json')['context']['lmcp'])
    info = release.load(lmcp / 'build-info.json')
    def mixed(folder):
        altered = copy.deepcopy(info); altered['generationRunId'] = 'unrelated-generation'
        release.save(folder / 'mixed-info.json', altered)
        release.lmcp.check_package(task.root, lmcp, altered, info['inputs'], task.baseline['provenance']['packages']['generationRunId'])
    reject('mixed-lmcp-generation', mixed, 'identity')
    package.save(task.run / 'source-faults.json', dict(status='passed', cases=results,
        scope='Isolated copies/metadata passed to unmodified production validators', qualifiedPackagesUnchanged=True))
    task.record['sourceFaults'] = results


def child(task, label, mode='Headless', fault='', chinese=False):
    require, save, load, sha = task.amase.require, task.amase.save, task.amase.load, task.amase.sha
    require(time.monotonic() < task.operation_deadline, 'timeout:whole-run')
    run_id = task.args.run_id + '-' + label
    folder = task.root / 'out/runs' / run_id; folder.mkdir()
    context = dict(task.context, mode=mode, verify=False, parentRunId=task.args.run_id,
                   operationDeadline=task.operation_deadline)
    save(folder / 'context.json', context)
    cwd = task.run / ('其他 工作目录' if chinese else 'other-working-directory')
    cwd.mkdir(exist_ok=True)
    argv = [sys.executable, '-I', '-B', '-X', 'utf8', str(task.root / 'scripts/g3_stability/runtime.py'),
            '--root', str(task.root), '--run-id', run_id, '--mode', mode]
    if fault: argv += ['--fault', fault]
    if chinese: argv += ['--chinese-path']
    started = time.monotonic()
    print('T06 starting ' + label + ' / ' + mode, flush=True)
    with (folder / 'controller.stdout').open('wb', buffering=0) as output, (folder / 'controller.stderr').open('wb', buffering=0) as error:
        process = subprocess.Popen(argv, cwd=cwd, stdout=output, stderr=error, creationflags=subprocess.CREATE_NO_WINDOW)
        next_log = time.monotonic() + 25
        while process.poll() is None:
            if time.monotonic() >= task.operation_deadline: (folder / 'request-abort').touch(exist_ok=True)
            if time.monotonic() >= task.operation_deadline + 45:
                # Only this still-live owned controller and its descendants are targeted.
                killed = subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                    capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                save(folder / 'controller-timeout.json', dict(status='failed', pid=process.pid,
                    forcedTermination=True, taskkillExitCode=killed.returncode, error='timeout:controller-cleanup'))
                process.wait(timeout=5)
                raise RuntimeError('timeout:controller-cleanup; owned tree terminated, see ' + run_id)
            if time.monotonic() >= next_log:
                lines = (folder / 'controller.stdout').read_text(encoding='utf-8', errors='replace').splitlines()
                print('T06 ' + label + ': ' + (lines[-1] if lines else 'qualifying/starting'), flush=True)
                next_log = time.monotonic() + 25
            time.sleep(0.2)
        process.wait()
    result = load(folder / 'result.json')
    row = dict(name=label, runId=run_id, mode=mode, fault=fault, status=result['status'], exitCode=process.returncode,
               controllerPid=process.pid, controllerReaped=True, invocationDirectory=cwd.relative_to(task.root).as_posix(),
               elapsedSeconds=time.monotonic() - started, resultSHA256=sha(folder / 'result.json'))
    save(folder / 'controller-result.json', row)
    task.record['cases'].append(row)
    save(task.run / 'result.json', task.record)
    require(result['runId'] == run_id and result['task'] == 'G3-T06', 'Child run identity mismatch')
    require(len(result['cases']) == 1, label + ': child failed before runtime case: ' + result.get('error', ''))
    case = result['cases'][0]
    require(load(folder / case['name'] / 'case-result.json') == case, 'Child case differs from result')
    task.amase.verify_records(folder / case['name'], case['evidence'])
    require(row['exitCode'] == (0 if result['status'] == 'passed' else 1), 'Child status/exit mismatch')
    row['caseSHA256'] = sha(folder / case['name'] / 'case-result.json')
    row['processes'] = case['processes']
    print('T06 ' + label + ': child ' + row['status'] + ' / ' + case.get('error', 'actual execution passed'), flush=True)
    return row, case, folder / case['name']


def normal(task, label, mode='Headless', chinese=False):
    row, case, directory = child(task, label, mode, chinese=chinese)
    task.amase.require(row['status'] == 'passed' and case['status'] == 'passed' and case['normalExit'] and
        case['portsReleased'] and case['planningReceipt']['actualExecutionValidated'] and
        case['simulationRate']['status'] == 'passed' and all(p['exitCode'] == 0 and p['reaped'] and not p['forcedTermination']
        for p in case['processes']), label + ': normal execution/lifecycle failed')
    row.update(actualExecutionValidated=True, simulationRate=case['simulationRate'], isolation=case['isolation'])
    return row, case, directory


def expected(task, label, fault, diagnostic):
    row, case, directory = child(task, label, fault=fault)
    require = task.amase.require
    require(row['status'] == case['status'] == 'failed' and diagnostic in case.get('error', '') and case.get('portsReleased')
            and len(case['processes']) == 2 and all(p['reaped'] for p in case['processes']), label + ': unexpected fault result')
    if fault == 'shutdown-timeout':
        require(case['processes'][0]['forcedTermination'] and case['processes'][0]['exitCode'] != 0 and
                not case['processes'][1]['forcedTermination'] and case['processes'][1]['exitCode'] == 0, 'Wrong timeout ownership')
        phases = {r['phase']: r['monotonicSeconds'] for r in case['transitions']}
        require(30 <= phases['shutdown-finished'] - phases['shutdown-requested'] < 42, 'Shutdown deadline differs')
    else:
        require(case['normalExit'] and not any(p['forcedTermination'] for p in case['processes']), 'Fault cleanup was not normal')
        if fault == 'planning-timeout':
            timeout = next(r for r in case['transitions'] if r['phase'] == 'planning-response-timeout')
            require(30 <= timeout['elapsedSeconds'] < 35, 'Planning deadline differs')
        if fault.endswith('early-exit'):
            require(case['injectedEarlyExit']['exitCode'] == 0 and not any(t['phase'] == 'execution-observed' for t in case['transitions']),
                    'Early normal exit was not rejected before execution')
    row.update(expectedFailureVerified=True, diagnostic=case['error'], rawFailurePreserved=True)
    return row, case, directory


def disconnect_check(task, directory, case):
    import importlib.util
    spec = importlib.util.spec_from_file_location('stability_wire', task.root / 'scripts/g3_protocol/wire.py')
    wire = importlib.util.module_from_spec(spec); spec.loader.exec_module(wire)
    require, save = task.amase.require, task.amase.save
    data = (directory / 'amase-to-uxas-forwarded.bin').read_bytes()
    reader = wire.sentinel.SentinelReader(); frames = reader.feed(data)
    pending = bytes(reader.buffer); receipt = case['disconnect']
    require(frames and pending == (directory / 'cut-prefix.bin').read_bytes() and
            reader.offset == receipt['destinationFrameOffset'] and len(pending) == receipt['sentBytes'], 'Partial boundary not reproduced')
    try: reader.eof()
    except ValueError as error: diagnostic = str(error)
    else: raise RuntimeError('Partial frame falsely accepted at EOF')
    full = wire.sentinel.SentinelReader().feed((directory / 'cut-frame.bin').read_bytes())
    require(len(full) == 1 and len(data) == reader.offset + len(pending), 'Recorded cut was not a real complete source frame')
    decoded, _ = wire.sentinel.Decoder(task.factory).decode(full[0])
    # Only complete messages reached the bus; the severed message cannot be imported.
    rows = [json.loads(line) for line in (directory / 'observer.jsonl').read_text(encoding='utf-8').splitlines()]
    if decoded['type'] == 'afrl.cmasi.AirVehicleState':
        require(not any(r['type'] == decoded['type'] and r.get('id') == decoded['id'] and r.get('timeMs') == decoded['timeMs']
                        for r in rows), 'Truncated vehicle state reached UxAS')
    result = dict(status='passed', frame=decoded, completedFrames=len(frames), pendingBytes=len(pending),
                  frameOffset=reader.offset, eofDiagnostic=diagnostic, sourceFrameSHA256=task.amase.sha(directory / 'cut-frame.bin'),
                  bytesPreserved=True, incompleteMessageNotImported=True)
    save(task.run / 'disconnect-check.json', result)
    return result


def verify(task):
    require, save = task.amase.require, task.amase.save
    isolated_sources(task)
    normal(task, 'repeat-1')
    normal(task, 'repeat-2', chinese=True)
    normal(task, 'repeat-3', 'Gui')
    with socket.socket() as occupied:
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        occupied.bind(('127.0.0.1', task.config['modes']['Headless']['amasePort'])); occupied.listen(1)
        row, case, _ = child(task, 'port-conflict')
        require(row['status'] == case['status'] == 'failed' and not case['processes'] and not case['injections'] and
                'port' in case['error'].lower(), 'Conflict did not reject before launching')
        with socket.create_connection(occupied.getsockname(), timeout=1):
            peer, _ = occupied.accept(); peer.close()
        row.update(expectedFailureVerified=True, foreignListenerPreserved=True, rawFailurePreserved=True)
    task.amase.check_port(task.config['modes']['Headless']['amasePort'])
    expected(task, 'amase-early-exit', 'amase-early-exit', 'process-exited:')
    expected(task, 'uxas-early-exit', 'uxas-early-exit', 'process-exited:')
    expected(task, 'planning-timeout', 'planning-timeout', 'timeout:planning-response')
    expected(task, 'shutdown-timeout', 'shutdown-timeout', 'timeout:shutdown')
    old, old_case, directory = expected(task, 'disconnect', 'disconnect-partial', 'disconnect:main-link-partial-frame')
    task.record['disconnectCheck'] = disconnect_check(task, directory, old_case)
    new, new_case, _ = normal(task, 'fresh-group', chinese=True)
    require(new['runId'] != old['runId'] and not ({p['pid'] for p in old_case['processes']} &
                                               {p['pid'] for p in new_case['processes']}), 'Failed group was reused')
    task.record['recovery'] = dict(status='passed', failedRunId=old['runId'], freshRunId=new['runId'],
        oldChildrenReaped=True, oldPortsReleased=True, freshExecutionValidated=True,
        freshIdentity=new_case['isolation'], scope='Whole group restart; no online reconnect or task resume')
    task.record['isolationCounterexamples'] = isolation_checks(task, new, new_case)
    # Check the actual controller budget guard independently of process state.
    original_deadline = task.operation_deadline
    try:
        task.operation_deadline = time.monotonic() - 1
        try: task.alive()
        except RuntimeError as error: require(str(error) == 'timeout:whole-run', 'Wrong whole-run rejection')
        else: raise RuntimeError('Expired budget was accepted')
    finally: task.operation_deadline = original_deadline
    task.record['wholeRunBudgetCheck'] = dict(automaticSeconds=2700, operationSeconds=2650, cleanupReserveSeconds=50, passed=True)
    require(task.protected_files() == task.protected, 'Qualified packages/source receipts changed')
    save(task.run / 'acceptance.json', dict(task='G3-T06', runId=task.args.run_id, status='passed',
        cases=task.record['cases'], sourceFaults=task.record['sourceFaults'], recovery=task.record['recovery'],
        disconnectCheck=task.record['disconnectCheck'], taskExecutionValidated=True,
        isolationCounterexamples=task.record['isolationCounterexamples'], wholeRunBudgetCheck=task.record['wholeRunBudgetCheck'],
        sourceFaultsSHA256=task.amase.sha(task.run / 'source-faults.json'),
        disconnectCheckSHA256=task.amase.sha(task.run / 'disconnect-check.json'),
        isolationChecksSHA256=task.amase.sha(task.run / 'isolation-checks.json'),
        fullTaskRerun=False, completionReference=task.record['completionReference'], qualifiedPackagesUnchanged=True))
    task.record['acceptanceSHA256'] = task.amase.sha(task.run / 'acceptance.json')


def isolation_checks(task, row, case):
    import importlib.util
    spec = importlib.util.spec_from_file_location('isolation_checks', task.root / 'scripts/g3_stability/isolation.py')
    audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
    directory = task.root / 'out/runs' / row['runId'] / case['name']
    rows = lambda name: [json.loads(line) for line in (directory / name).read_text(encoding='utf-8').splitlines()]
    observer, monitor, events = rows('observer.jsonl'), rows('amase.jsonl'), rows('amase/events.jsonl')
    audit.assess(row['runId'], case['name'], case, observer, monitor, events)
    results = ['unaltered-positive']
    for name, diagnostic in [('rate-change', 'rate differs'), ('stale-readiness', 'token leaked'),
                             ('old-byte-offset', 'byte zero'), ('old-completion', 'Unexpected completion'),
                             ('old-clock', 'time zero'), ('old-task', 'Task state preceded'),
                             ('old-command', 'Planned command preceded')]:
        obs, mon, ev = copy.deepcopy((observer, monitor, events))
        if name == 'rate-change': next(r for r in mon if r['type'] == 'afrl.cmasi.SessionStatus' and r['state'] == 1)['realTimeMultiple'] = 10
        elif name == 'stale-readiness': next(r for r in mon if r.get('key') == 'G3Ready')['value'] = 'previous-run/token'
        elif name == 'old-byte-offset': obs[0]['offset'] = 289
        elif name == 'old-clock': next(e for e in ev if e['kind'] == 'initialized-paused')['simTimeSeconds'] = '740.709'
        elif name == 'old-command':
            cruises = {audit.command_content(r) for r in mon if r['type'] == 'afrl.cmasi.MissionCommand' and r.get('commandId') == '100'}
            command = copy.deepcopy(next(r for r in obs if r['type'] == 'afrl.cmasi.MissionCommand' and audit.command_content(r) not in cruises))
            command['monotonicSeconds'] = 0; obs.append(command)
        else:
            kind = {'old-completion':'uxas.messages.task.TaskComplete', 'old-task':'uxas.messages.task.TaskActive',
                    'old-command':'afrl.cmasi.MissionCommand'}[name]
            obs.append(dict(type=kind, commandId='999', monotonicSeconds=0))
        try: audit.assess(row['runId'], case['name'], case, obs, mon, ev)
        except RuntimeError as error: task.amase.require(diagnostic in str(error), 'Wrong isolation rejection: ' + str(error))
        else: raise RuntimeError('Isolation mutation was accepted: ' + name)
        results.append(name)
    result = dict(status='passed', sourceRunId=row['runId'], tests=results, syntheticMutationsOfRealCapture=True)
    task.amase.save(task.run / 'isolation-checks.json', result)
    return result
