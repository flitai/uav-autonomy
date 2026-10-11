"""Exercise the B08 task workflow entirely through a real Edge page."""
import argparse
import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
from urllib.request import urlopen

from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('b05_browser', ROOT / 'tests/g6_assignment/browser.py')
b05 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b05)
flow = b05.flow


async def verify(output, session, relationship):
    output.mkdir(parents=True, exist_ok=False)
    result = dict(task='G6-B08', status='running', mode=relationship,
                  backendMode=session.parent.parent.name, steps=[])
    edge = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft/Edge/Application/msedge.exe'
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(('127.0.0.1', 9228))
    args = [str(edge), '--headless=new', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-background-mode', '--disable-extensions',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9228',
            '--window-size=1920,1080', '--user-data-dir=' + str(output / 'profile'), 'about:blank']
    process = ws = client = None
    with (output / 'stdout.log').open('wb') as stdout, (output / 'stderr.log').open('wb') as stderr:
        try:
            code, state = flow.http(8005, 'GET', '/api/tasks/v2/state')
            flow.need(code == 200 and state['identity']['runId'] == session.parent.parent.name,
                      'B08 session identity differs')
            process = subprocess.Popen(args, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            version = None
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                flow.need(process.poll() is None, 'Edge exited before CDP startup')
                try:
                    with urlopen('http://127.0.0.1:9228/json/version', timeout=.5) as response:
                        version = json.load(response)
                    break
                except OSError:
                    await asyncio.sleep(.1)
            flow.need(version is not None, 'Edge CDP unavailable')
            ws = await connect(version['webSocketDebuggerUrl'], max_size=32*1024*1024)
            client = b05.cdp.DevTools(ws)
            target = await client.call('Target.createTarget', {'url': 'about:blank'})
            tab = (await client.call('Target.attachToTarget',
                   {'targetId': target['targetId'], 'flatten': True}))['sessionId']
            for method in ('Page.enable', 'Runtime.enable', 'Network.enable'):
                await client.call(method, session=tab)
            await client.call('Page.navigate', {'url': 'http://127.0.0.1:8080/'}, session=tab)

            async def evaluate(expression):
                reply = await client.call('Runtime.evaluate',
                    {'expression': expression, 'returnByValue': True, 'awaitPromise': True},
                    session=tab)
                if reply.get('exceptionDetails'):
                    raise RuntimeError('Browser expression failed: ' + str(reply['exceptionDetails']))
                return reply.get('result', {}).get('value')

            async def until(expression, predicate, seconds=50):
                deadline = time.monotonic() + seconds
                last = None
                while time.monotonic() < deadline:
                    flow.need(process.poll() is None, 'Edge exited during B08 interaction')
                    last = await evaluate(expression)
                    if predicate(last):
                        return last
                    await asyncio.sleep(.2)
                raise TimeoutError('Browser timeout: ' + expression + ' last=' + str(last)[:500])

            async def field(name, value, event='input'):
                return await evaluate("(()=>{const e=document.getElementById(" + json.dumps(name) +
                    ");e.value=" + json.dumps(value) + ";e.dispatchEvent(new Event('" + event +
                    "',{bubbles:true}));return e.value;})()")

            async def click(name):
                await evaluate("document.getElementById(" + json.dumps(name) + ").click()")

            tasks = 'window.__g6Tasks?.inspect()'
            await until(tasks, lambda x: x and x['ready'] and len(x['items']) == 0, 70)
            basemap = await until("(()=>({base:document.querySelector('#base-layer')?.value,"
                "ready:document.documentElement.dataset.ready,layers:window.__g5Map?.viewer.imageryLayers.length}))()",
                lambda x: x and x.get('base') == 'local' and x.get('ready') == 'true' and
                x.get('layers') == 1, 50)
            result['steps'].append(dict(action='offline-local-vector', state=basemap))

            geometry = {
                'line': {'line': '-120.9923, 45.3171\n-120.9800, 45.3171'},
                'point': {'longitude': '-120.7645' if relationship == 'parallel' else '-120.977',
                          'latitude': '45.323'},
                'area': {'longitude': '-120.979' if relationship == 'parallel' else '-120.974',
                         'latitude': '45.323' if relationship == 'parallel' else '45.325',
                         'width': '500', 'height': '300'}}
            drafts = {}
            for index, kind in enumerate(('line', 'point', 'area'), start=1):
                await field('task-kind', kind, 'change')
                for key, value in geometry[kind].items():
                    await field('task-' + key, value)
                await click('task-save')
                snapshot = await until(tasks, lambda x: x and len(x['items']) == index and
                                       x['selected'] and not x['dirty'], 35)
                draft = next(item['draft'] for item in snapshot['items']
                             if item['draft']['draftId'] == snapshot['selected'])
                flow.need(draft['kind'] == kind, 'Saved draft kind differs')
                drafts[kind] = draft
                result['steps'].append(dict(action='create-' + kind, draftId=draft['draftId'],
                                           revision=draft['revision'], taskId=draft['taskId']))

            await client.call('Page.reload', {'ignoreCache': True}, session=tab)
            restored = await until(tasks, lambda x: x and x['ready'] and len(x['items']) == 3, 50)
            flow.need({item['draft']['draftId'] for item in restored['items']} ==
                      {draft['draftId'] for draft in drafts.values()},
                      'Page refresh did not restore all draft versions')
            result['steps'].append(dict(action='refresh-drafts', count=3))

            assignment = 'window.__g6Assignment?.inspect()'
            await until(assignment, lambda x: x and x['state'] and
                        len(x['state']['drafts']) == 3, 65)
            await evaluate("document.getElementById('multi-task-planning').open=true")
            await field('multi-relationship', relationship, 'change')
            selected = await evaluate("(()=>({count:document.querySelectorAll('.multi-task-card').length,"
                "disabled:document.getElementById('multi-preview').disabled}))()")
            flow.need(selected['count'] == 3 and not selected['disabled'],
                      'Three UI drafts were not selected for joint planning')
            await click('multi-preview')
            planned = await until(assignment, lambda x: x and x['review'] and
                                  x['review']['planId'], 80)
            review = planned['review']
            assigned = {item['vehicleId'] for item in review['plan']['assignments']}
            flow.need(review['relationship'] == relationship and review['confirmationAllowed'] and
                      len(review['plan']['assignments']) == 3 and
                      (len(assigned) >= 2 if relationship == 'parallel' else assigned == {'400'}),
                      'UI review does not have the qualified assignment')
            flow.need(await evaluate("document.getElementById('multi-confirm').disabled"),
                      'Unacknowledged plan can be submitted')
            result['review'] = review
            await evaluate("document.getElementById('multi-task-planning').scrollIntoView({block:'start'})")
            shot = await client.call('Page.captureScreenshot', {'format': 'png'}, session=tab)
            (output / 'review.png').write_bytes(base64.b64decode(shot['data']))
            await evaluate("(()=>{const e=document.getElementById('multi-ack');e.checked=true;"
                           "e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            flow.need(not await evaluate("document.getElementById('multi-confirm').disabled"),
                      'Acknowledged plan is disabled')
            await click('multi-confirm')
            confirmed = await until(assignment, lambda x: x and x['confirmationKey'], 80)
            key = confirmed['confirmationKey']
            def confirmed_receipt():
                code, row = flow.http(8005, 'GET', '/api/tasks/v2/confirmations/' + key)
                return row if code == 200 and row['status'] in ('confirmed', 'executing', 'completed') else None
            receipt = flow.wait('UI confirmation reached backend', confirmed_receipt, 80)
            result['steps'].append(dict(action='confirm', key=key, phase=receipt['phase']))

            await until("!document.getElementById('control-pause').disabled", bool, 35)
            await click('control-pause')
            paused = await until("document.getElementById('control-resume').disabled===false", bool, 35)
            flow.need(paused, 'Simulation did not pause through page control')
            await click('control-resume')
            await until("document.getElementById('control-pause').disabled===false", bool, 35)
            await field('control-rate', '10', 'change')
            await until("document.getElementById('control-set-rate').disabled===false", bool, 20)
            await click('control-set-rate')
            await until("(()=>{const p=document.querySelector('#simulation-controls progress');"
                        "return p&&!p.hidden})()", bool, 35)
            result['steps'].append(dict(action='page-controls', pause=True, resume=True,
                                       rate='10', progressVisible=True))

            def complete():
                code, row = flow.http(8005, 'GET', '/api/tasks/v2/confirmations/' + key)
                flow.need(code == 200, 'Confirmation became unavailable')
                return row if row['status'] == 'completed' else None
            receipt = flow.wait('B08 task completion', complete, 330)
            result['receipt'] = receipt
            result['audit'] = flow.audit(session, review, receipt, relationship)
            await evaluate("document.getElementById('multi-task-planning').scrollIntoView({block:'start'})")
            shot = await client.call('Page.captureScreenshot', {'format': 'png'}, session=tab)
            (output / 'completed.png').write_bytes(base64.b64decode(shot['data']))
            result['steps'].append(dict(action='complete', tasks=len(receipt['tasks'])))
            result['status'] = 'passed'
        except Exception as error:
            result.update(status='failed', error=str(error), traceback=traceback.format_exc())
            print(result['traceback'], file=sys.stderr)
        finally:
            if client is not None:
                try:
                    await client.call('Browser.close')
                except Exception:
                    pass
            if ws is not None:
                await ws.close()
            if process is not None:
                try:
                    process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    result['status'] = 'failed'
                    result['edgeForcedTermination'] = True
                result['edgeExitCode'] = process.returncode
            (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                                                encoding='utf-8')
    return 0 if result['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--relationship', choices=('parallel', 'sequence'), required=True)
    args = parser.parse_args()
    return asyncio.run(verify(args.output.resolve(), args.session.resolve(), args.relationship))


if __name__ == '__main__':
    sys.exit(main())
