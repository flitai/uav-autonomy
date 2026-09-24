"""Exercise the persistent G6 control entry and a real two-segment reset."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_control'))
import api_probe

c = api_probe.c


def wait(label, predicate, process, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        c.need(process.poll() is None, label + ': session process exited')
        try:
            result = predicate()
            if result:
                return result
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError(label + ': timeout')


def post(session, key, action):
    code, state = api_probe.http('GET', '/state')
    c.need(code == 200, 'Control state unavailable')
    value = dict(runId=session['runId'], segmentId=session['segmentId'],
                 expectedSequence=state['controlSequence'], idempotencyKey=key,
                 action=action, multiple=None)
    code, result = api_probe.http('POST', '/operations', value)
    c.need(code in (200, 202) and result['key'] == key, 'Control command failed: ' + str((code, result)))
    return result


def run_mode(root_run, mode, viewer_build, browser_reset=False):
    identity = 'g6-control-' + root_run + '-' + mode.lower()
    directory = ROOT / 'out/runs' / identity
    logs = ROOT / 'out/runs' / root_run
    with (logs / (mode.lower() + '.stdout')).open('wb') as stdout, \
         (logs / (mode.lower() + '.stderr')).open('wb') as stderr:
        process = subprocess.Popen([sys.executable, '-I', '-B', '-X', 'utf8',
            str(ROOT / 'scripts/g6_control/session.py'), '--run-id', identity,
            '--viewer-build', viewer_build, '--mode', mode],
            cwd=ROOT, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            first = wait('first segment ready', lambda: c.load(directory / 'session-ready.json')
                         if (directory / 'session-ready.json').is_file() else None, process, 90)
            c.need(first['segmentId'] == 'segment-001-1', 'First segment identity differs')
            if browser_reset:
                output = logs / (mode.lower() + '-browser')
                _, _, browser_python = api_probe.probe.state.entry.resolve(ROOT)
                with (logs / (mode.lower() + '-browser.stdout')).open('wb') as browser_out, \
                     (logs / (mode.lower() + '-browser.stderr')).open('wb') as browser_err:
                    browser = subprocess.run([str(browser_python), '-I', '-B', '-X', 'utf8',
                        str(ROOT / 'tests/g6_control/browser.py'), '--output', str(output),
                        '--scenario', 'reset'], cwd=ROOT, stdout=browser_out, stderr=browser_err,
                        timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
                browser_result = c.load(output / 'result.json')
                c.need(browser.returncode == 0 and browser_result['status'] == 'passed' and
                       len(browser_result['steps']) == 5 and not browser_result['forcedTermination'],
                       'Real browser reset failed')
                reset_key = None
            else:
                post(first, 'smoke-start-0001', 'start')
                wait('first start confirmed', lambda: api_probe.http('GET',
                     '/operations/smoke-start-0001')[1]['status'] == 'confirmed', process)
                reset = post(first, 'smoke-reset-0001', 'reset')
                c.need(reset['status'] == 'pending', 'Reset was not queued')
                reset_key = 'smoke-reset-0001'
            second = wait('second segment ready', lambda: (value if (value := c.load(directory / 'session-ready.json'))
                 ['segmentId'] != first['segmentId'] else None), process, 90)
            c.need(second['backendRunId'] != first['backendRunId'], 'Reset reused backend run')
            if browser_reset:
                receipt_file = next((directory / 'control-reset-receipts').glob('*.json'))
                reset_key = receipt_file.stem
            code, receipt = api_probe.http('GET', '/operations/' + reset_key)
            c.need(code == 200 and receipt['status'] == 'confirmed' and
                   receipt['toSegmentId'] == second['segmentId'], 'Reset receipt missing')
            code, current = api_probe.http('GET', '/state')
            c.need(code == 200 and current['segmentId'] == second['segmentId'] and
                   (current['simulation']['state'] == 2 if browser_reset else not current['ready']),
                   'New segment state differs')
            code, stale = api_probe.http('POST', '/operations', dict(runId=first['runId'],
                segmentId=first['segmentId'], expectedSequence=current['controlSequence'],
                idempotencyKey='smoke-stale-0001', action='start', multiple=None))
            c.need(code == 409, 'Old segment action was accepted')
            if not browser_reset:
                post(second, 'smoke-start-0002', 'start')
                wait('second start confirmed', lambda: api_probe.http('GET',
                     '/operations/smoke-start-0002')[1]['status'] == 'confirmed', process)
                post(second, 'smoke-pause-0002', 'pause')
                wait('second pause confirmed', lambda: api_probe.http('GET',
                     '/operations/smoke-pause-0002')[1]['status'] == 'confirmed', process)
            (directory / 'request-stop').touch()
            process.wait(timeout=80)
            result = c.load(directory / 'runtime-result.json')
            c.need(process.returncode == 0 and result['status'] == 'passed' and
                   result['normalExit'] and result['segments'] == 2 and
                   all(case['status'] == 'passed' and case['normalExit'] and case['portsReleased']
                       for case in result['cases']), 'Persistent control session did not close normally')
            return dict(runId=identity, first=first, second=second, resetReceipt=receipt,
                        runtimeSHA256=c.sha(directory / 'runtime-result.json'), exitCode=process.returncode,
                        browserReset=browser_reset)
        finally:
            if process.poll() is None:
                (directory / 'request-stop').touch()
                try:
                    process.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--viewer-build', required=True)
    parser.add_argument('--browser-reset', action='store_true')
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    c.need(args.run_id.startswith('g6-a05-smoke-') and not run.exists(), 'Invalid smoke run')
    run.mkdir(parents=True)
    record = dict(task='G6-A05', runId=args.run_id, status='running',
                  viewerBuildRunId=args.viewer_build, controlRuntimeQualified=False, modes=[])
    try:
        for mode in ('Headless', 'Gui'):
            record['modes'].append(run_mode(args.run_id, mode, args.viewer_build, args.browser_reset))
        record.update(status='passed', twoModePersistentResetObserved=True)
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], flush=True)
        return 1
    finally:
        c.save(run / 'result.json', record)


if __name__ == '__main__':
    sys.exit(main())
