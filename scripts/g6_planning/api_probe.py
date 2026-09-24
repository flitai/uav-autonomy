"""G6-B02 real HTTP preview and active-group isolation check."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_control'))
import api_probe as control
sys.path.insert(0, str(ROOT / 'scripts/g6_planning'))
import isolated_preview

load, save, need = control.c.load, control.c.save, control.c.need
URL = 'http://127.0.0.1:8002/api/tasks/v1'


def http(method, path, value=None, origin=True):
    headers = {'Origin': 'http://127.0.0.1:8080'} if origin else {}
    payload = None
    if value is not None:
        headers['Content-Type'] = 'application/json'
        payload = json.dumps(value, ensure_ascii=False).encode('utf-8')
    request = Request(URL + path, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=65) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def wait(label, predicate, process, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        need(process.poll() is None, label + ': process exited')
        try:
            value = predicate()
            if value:
                return value
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError(label + ': timeout')


def ready_state():
    code, value = http('GET', '/state')
    return value if code == 200 else None


def mode_case(root_run, mode, viewer_build, web_python):
    session_id = 'g6-control-' + root_run + '-' + mode.lower()
    session_run = ROOT / 'out/runs' / session_id
    run = ROOT / 'out/runs' / root_run
    session_process = service_process = None
    result = None
    try:
        with (run / (mode.lower() + '-session.stdout')).open('wb') as out, \
             (run / (mode.lower() + '-session.stderr')).open('wb') as err:
            session_process = subprocess.Popen([sys.executable, '-I', '-B', '-X', 'utf8',
                str(ROOT / 'scripts/g6_control/session.py'), '--run-id', session_id,
                '--viewer-build', viewer_build, '--mode', mode], cwd=ROOT,
                stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        ready = wait('active session', lambda: load(session_run / 'session-ready.json')
                     if (session_run / 'session-ready.json').is_file() else None,
                     session_process)
        session_file = session_run / 'segment-001' / 'control-session.json'
        before = wait('frozen active snapshot',
                      lambda: isolated_preview.active_evidence(session_file),
                      session_process, 45)
        with (run / (mode.lower() + '-api.stdout')).open('wb') as out, \
             (run / (mode.lower() + '-api.stderr')).open('wb') as err:
            service_process = subprocess.Popen([str(web_python), '-I', '-B', '-X', 'utf8',
                str(ROOT / 'apps/g6_tasks/server.py'), '--session', str(session_file)],
                cwd=ROOT, stdout=out, stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW)
        state = wait('preview API', ready_state, service_process, 20)
        need(state == {key: before[key] for key in state}, 'Preview state binding differs')
        rows = []
        samples = ROOT / 'out/runs/g6-b01-baseline-20260924-2223/samples'
        for index, kind in enumerate(('line', 'point', 'area'), start=1):
            draft = copy.deepcopy(load(samples / (kind + '-draft.json')))
            draft.update(runId=ready['runId'], segmentId=ready['segmentId'],
                         draftId=mode.lower() + '-' + kind)
            body = dict(runId=ready['runId'], segmentId=ready['segmentId'],
                        backendRunId=ready['backendRunId'], streamId=before['streamId'],
                        revision=draft['revision'], idempotencyKey='g6-b02-' + mode.lower() + '-' + kind,
                        draft=draft)
            code, row = http('POST', '/previews', body)
            need(code == 200 and row['status'] == 'previewed' and
                 row['plan']['taskId'] == draft['taskId'] and
                 row['plan']['route']['waypointCount'] >= 2 and
                 not row['plan']['confirmationEnabled'],
                 kind + ' preview failed: ' + str((code, row)))
            code, repeated = http('POST', '/previews', body)
            need(code == 200 and row == repeated, 'Preview idempotency differs')
            code, queried = http('GET', '/plans/' + row['planId'])
            need(code == 200 and queried == row['plan'], 'Plan query differs')
            rows.append(dict(kind=kind, planId=row['planId'],
                             responseSHA256=row['plan']['responseSHA256'],
                             waypointCount=row['plan']['route']['waypointCount'],
                             previewRunId=row['previewRunId']))
            if index == 1:
                bad = copy.deepcopy(body)
                bad['draft']['geometry']['coordinates'][0] = [45.3, -120.9]
                need(http('POST', '/previews', bad)[0] == 409,
                     'Changed input reused idempotency key')
                bad['idempotencyKey'] = 'g6-b02-bad-geometry-' + mode.lower()
                need(http('POST', '/previews', bad)[0] == 422,
                     'Invalid geometry was accepted')
                stale = copy.deepcopy(body)
                stale['idempotencyKey'] = 'g6-b02-stale-' + mode.lower()
                stale['streamId'] = 'old-stream'
                need(http('POST', '/previews', stale)[0] == 409,
                     'Stale stream was accepted')
                need(http('POST', '/previews', body, origin=False)[0] == 403,
                     'Untrusted origin was accepted')
                need(http('POST', '/plans/' + row['planId'] + '/confirm', body)[0] == 404,
                     'Unqualified execution route is exposed')
        after = isolated_preview.active_evidence(session_file)
        need(before['forbiddenRows'] == after['forbiddenRows'],
             'Active command or planning request changed')
        result = dict(mode=mode, status='passed', activeBefore=before, activeAfter=after,
                      previews=rows, negativeCases=5)
    finally:
        if service_process is not None:
            service_process.terminate()
            try:
                service_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                service_process.kill(); service_process.wait()
        if session_process is not None:
            (session_run / 'request-stop').touch(exist_ok=True) if session_run.exists() else None
            try:
                session_process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                session_process.kill(); session_process.wait()
    need(result is not None and session_process.returncode == 0,
         'Active ' + mode + ' session did not exit normally')
    runtime = load(session_run / 'runtime-result.json')
    need(runtime['status'] == 'passed' and runtime['normalExit'] and
         runtime['segments'] == 1, 'Active ' + mode + ' runtime receipt failed')
    result['activeSessionNormalExit'] = True
    result['activeRuntimeSHA256'] = control.c.sha(session_run / 'runtime-result.json')
    return result


def negative_case(root_run, fault):
    run = ROOT / 'out/runs' / root_run
    draft = run / (fault + '-draft.json')
    value = load(ROOT / 'out/runs/g6-b01-baseline-20260924-2223/samples/point-draft.json')
    if fault == 'unknown-task-type':
        value['kind'] = 'unknown'
    save(draft, value)
    identity = root_run + '-' + fault
    command = [sys.executable, '-I', '-B', '-X', 'utf8',
               str(ROOT / 'scripts/g6_planning/isolated_preview.py'),
               '--run-id', identity, '--draft', str(draft)]
    if fault != 'unknown-task-type':
        command += ['--fault', fault]
    result = subprocess.run(command, cwd=ROOT, capture_output=True,
                            timeout=50, creationflags=subprocess.CREATE_NO_WINDOW)
    (run / (fault + '.stdout')).write_bytes(result.stdout)
    (run / (fault + '.stderr')).write_bytes(result.stderr)
    receipt = load(ROOT / 'out/runs' / identity / 'result.json')
    expected = 'Unsupported task type' if fault == 'unknown-task-type' else 'timed out'
    need(result.returncode == 1 and receipt['status'] == 'failed' and
         expected in receipt['error'] and not receipt.get('forcedTermination') and
         receipt.get('exitCode', 0) == 0,
         'Negative ' + fault + ' did not fail closed: ' + str(receipt.get('error')))
    return dict(fault=fault, status='rejected', error=receipt['error'],
                runId=identity, plannerNormalExit=receipt.get('exitCode', 0) == 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    need(args.run_id.startswith('g6-b02-'), 'B02 run ID required')
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'B02 run ID exists')
    run.mkdir(parents=True)
    record = dict(task='G6-B02', runId=args.run_id, status='running',
                  previewIsolationQualified=False, executionQualified=False,
                  cases=[], negativeCases=[])
    try:
        sources = [ROOT / path for path in (
            'apps/g6_tasks/server.py', 'scripts/g6_planning/api_probe.py',
            'scripts/g6_planning/isolated_preview.py', 'scripts/g6_planning/task_input.py',
            'config/g6-task-contract-v1.json')]
        record['sources'] = [dict(path=path.relative_to(ROOT).as_posix(),
                                  sha256=control.c.sha(path)) for path in sources]
        _, _, web_python = control.probe.state.entry.resolve(ROOT)
        production = load(ROOT / 'out/runs/g6-control-production-check-20260924-2215-session/source-binding.json')
        viewer = production['viewerBuildRunId']
        for mode in ('Headless', 'Gui'):
            record['cases'].append(mode_case(args.run_id, mode, viewer, web_python))
        for fault in ('unknown-task-type', 'wrong-response-id', 'planning-timeout'):
            record['negativeCases'].append(negative_case(args.run_id, fault))
        need(all(control.c.sha(ROOT / row['path']) == row['sha256']
                 for row in record['sources']), 'B02 source changed during validation')
        record.update(status='passed', previewIsolationQualified=True)
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], file=sys.stderr)
        return 1
    finally:
        save(run / 'acceptance.json', record)


if __name__ == '__main__':
    sys.exit(main())
