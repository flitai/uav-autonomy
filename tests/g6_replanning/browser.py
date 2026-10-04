"""Drive B05 confirmation and B06 task addition in a real Edge page."""
import argparse
import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from urllib.request import urlopen
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
for label, relative in (('cdp', 'tests/g5_entities/browser.py'),
                        ('flow', 'tests/g6_assignment/flow.py'),
                        ('live', 'scripts/g6_replanning/live.py')):
    spec = importlib.util.spec_from_file_location('g6_b06_' + label, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    globals()[label] = module


async def verify(output, session):
    output.mkdir(parents=True, exist_ok=False)
    result = dict(task='G6-B06', mode='add', status='running', browser='Microsoft Edge', steps=[])
    process = ws = client = None
    edge = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft/Edge/Application/msedge.exe'
    argv = [str(edge), '--headless=new', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-background-mode', '--disable-extensions',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9227',
            '--window-size=1920,1080', '--user-data-dir=' + str(output / 'profile'),
            'about:blank']
    with (output / 'stdout.log').open('wb') as stdout, \
         (output / 'stderr.log').open('wb') as stderr:
        try:
            code, state = flow.http(8005, 'GET', '/api/tasks/v2/state')
            flow.need(code == 200 and state['identity']['runId'] == session.parent.parent.name,
                      'Gui session identity differs')
            identity = state['identity']
            samples = ROOT / 'out/runs/g6-b01-baseline-20260924-2223/samples'
            geometry = {
                'line': dict(type='LineString', coordinates=[[-120.9923, 45.3171],
                                                         [-120.97, 45.3171]]),
                'point': dict(type='Point', coordinates=[-120.977, 45.323]),
                'area': dict(type='Rectangle', center=[-120.974, 45.325],
                             widthMeters=500, heightMeters=300, rotationDegrees=0)}
            for kind in ('line', 'point', 'area'):
                sample = flow.core.release.load(samples / (kind + '-draft.json'))
                body = dict(identity, idempotencyKey='g6-b06-browser-create-' + kind,
                            kind=kind, geometry=geometry[kind],
                            candidateEntityIds=sample['candidateEntityIds'],
                            altitudeDatum='EPSG:5773')
                code, created = flow.http(8003, 'POST', '/api/tasks/v1/drafts', body)
                flow.need(code in (200, 201) and created['status'] == 'confirmed',
                          'Gui draft creation failed: ' + str(created))
            process = subprocess.Popen(argv, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 25
            version = None
            while time.monotonic() < deadline:
                flow.need(process.poll() is None, 'Edge exited before CDP startup')
                try:
                    with urlopen('http://127.0.0.1:9227/json/version', timeout=.5) as response:
                        version = json.load(response)
                    break
                except Exception:
                    await asyncio.sleep(.1)
            flow.need(version is not None, 'Edge CDP unavailable')
            ws = await connect(version['webSocketDebuggerUrl'], max_size=32 * 1024 * 1024)
            client = cdp.DevTools(ws)
            target = await client.call('Target.createTarget', {'url': 'about:blank'})
            tab = (await client.call('Target.attachToTarget',
                   {'targetId': target['targetId'], 'flatten': True}))['sessionId']
            for method in ('Page.enable', 'Runtime.enable', 'Network.enable'):
                await client.call(method, session=tab)
            await client.call('Page.navigate', {'url': 'http://127.0.0.1:8080/'}, session=tab)

            async def evaluate(expression):
                answer = await client.call('Runtime.evaluate',
                    {'expression': expression, 'returnByValue': True, 'awaitPromise': True},
                    session=tab)
                if answer.get('exceptionDetails'):
                    raise RuntimeError('Browser expression failed: ' + str(answer['exceptionDetails']))
                return answer.get('result', {}).get('value')

            async def until(expression, predicate, seconds=60):
                deadline = time.monotonic() + seconds
                last = None
                while time.monotonic() < deadline:
                    flow.need(process.poll() is None, 'Edge exited during task interaction')
                    last = await evaluate(expression)
                    if predicate(last):
                        return last
                    await asyncio.sleep(.2)
                raise TimeoutError('Browser timeout: ' + expression + ' last=' + str(last)[:300])

            b05_inspect = 'window.__g6Assignment?.inspect()'
            b06_inspect = 'window.__g6Replanning?.inspect()'
            await until(b05_inspect, lambda x: x and x['state'] and len(x['state']['drafts']) == 3, 70)
            await until(b06_inspect, lambda x: x and x['state'] and
                        x['state']['status'] == 'pre-start', 70)
            await evaluate("document.getElementById('multi-task-planning').open=true")
            await evaluate("(()=>{const e=document.getElementById('multi-relationship');"
                           "e.value='sequence';e.dispatchEvent(new Event('change',{bubbles:true}));"
                           "const cards=document.querySelectorAll('.multi-task-card');"
                           "cards[2].querySelector('input[type=checkbox]').click();})()")
            selected = await evaluate("window.__g6Assignment.inspect()")
            flow.need(len(selected['state']['drafts']) == 3 and
                      not await evaluate("document.getElementById('multi-preview').disabled"),
                      'Browser could not select the initial two-task sequence')
            await evaluate("document.getElementById('multi-preview').click()")
            initial = (await until(b05_inspect, lambda x: x and x['review'] and
                                  len(x['review']['tasks']) == 2, 70))['review']
            flow.need(initial['confirmationAllowed'] and
                      {row['taskId'] for row in initial['tasks']} == {'3000', '3001'},
                      'Initial browser review differs')
            await evaluate("(()=>{const e=document.getElementById('multi-ack');e.checked=true;"
                           "e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            await evaluate("document.getElementById('multi-confirm').click()")
            initial_key = (await until(b05_inspect, lambda x: x and x['confirmationKey'] and
                not x['status'].startswith('正在确认'), 70))['confirmationKey']
            code, initial_receipt = flow.http(8005, 'GET',
                '/api/tasks/v2/confirmations/' + initial_key)
            flow.need(code == 200 and initial_receipt['status'] in
                      ('confirmed', 'executing', 'completed'),
                      'Initial browser confirmation did not reach the backend')
            result['steps'].append(dict(action='initial-confirm', planId=initial['planId'],
                                        key=initial_key))
            def active():
                rows = flow.core.observer_rows(session)
                old = [row for row in rows if row['type'] == 'uxas.messages.task.TaskActive'
                       and row.get('taskId') in ('3000', '3001')]
                completed = [row for row in rows if row['type'] ==
                             'uxas.messages.task.TaskComplete' and row.get('taskId') in ('3000', '3001')]
                flow.need(not completed, 'Old task completed before pause')
                return old if old else None
            flow.wait('Gui task active', active, 120)
            control = flow.http(8001, 'GET', '/api/control/v1/state')[1]
            code, pause = flow.http(8001, 'POST', '/api/control/v1/operations', dict(
                runId=identity['runId'], segmentId=identity['segmentId'],
                expectedSequence=control['controlSequence'],
                idempotencyKey='g6-b06-browser-pause', action='pause', multiple=None))
            flow.need(code in (200, 202), 'Gui pause rejected: ' + str(pause))
            flow.wait('Gui backend paused', lambda: (lambda row: row if row['simulation'] and
                row['simulation']['state'] == 2 else None)(flow.http(8001, 'GET',
                '/api/control/v1/state')[1]), 20)
            paused = flow.wait('Gui paused snapshot settled', lambda: snapshot_or_none(session), 20)
            await evaluate("document.getElementById('controlled-replanning').open=true")
            await until(b06_inspect, lambda x: x and x['state'] and
                        x['state']['status'] == 'paused' and
                        len(x['state']['availableDrafts']) == 1, 30)
            await evaluate("(()=>{const e=document.getElementById('replan-action');"
                           "e.value='add';e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            target = await evaluate("document.getElementById('replan-target').value")
            flow.need(target and target != '3002' and
                      not await evaluate("document.getElementById('replan-preview').disabled"),
                      'Browser could not select the saved additional task')
            result['steps'].append(dict(action='select-addition', draftId=target,
                                        pausedAtMs=paused['simulationTimeMs']))
            await evaluate("document.getElementById('replan-preview').click()")
            reviewed = await until(b06_inspect, lambda x: x and x['review'] and
                                   x['review']['planId'], 80)
            review = reviewed['review']
            flow.need(review['confirmationAllowed'] and review['change']['action'] == 'add' and
                      {row['taskId'] for row in review['tasks']} == {'3100', '3101', '3102'},
                      'Browser replacement review differs')
            comparison = await evaluate("document.getElementById('replan-review').textContent")
            flow.need('原方案：3000、3001；新版本：' in comparison,
                      'Browser review mislabels the newly added task as an old task')
            flow.need(await evaluate("document.getElementById('replan-confirm').disabled"),
                      'Browser allowed unacknowledged replacement')
            await evaluate("document.getElementById('controlled-replanning').scrollIntoView({block:'start'})")
            shot = await client.call('Page.captureScreenshot', {'format': 'png'}, session=tab)
            (output / 'review.png').write_bytes(base64.b64decode(shot['data']))
            await evaluate("(()=>{const e=document.getElementById('replan-ack');e.checked=true;"
                           "e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            flow.need(not await evaluate("document.getElementById('replan-confirm').disabled"),
                      'Acknowledged replacement remained disabled')
            await evaluate("document.getElementById('replan-confirm').click()")
            switch_key = (await until(b06_inspect, lambda x: x and x['key'] and
                not x['status'].startswith('正在切换'), 80))['key']
            code, switched = flow.http(8006, 'GET', '/api/tasks/v3/confirmations/' + switch_key)
            flow.need(code == 200 and switched['status'] in ('switched', 'executing', 'completed'),
                      'Browser replacement did not switch the backend')
            result['steps'].append(dict(action='confirm-replacement', key=switch_key,
                                        phase=switched['phase']))
            control = flow.http(8001, 'GET', '/api/control/v1/state')[1]
            code, rate = flow.http(8001, 'POST', '/api/control/v1/operations', dict(
                runId=identity['runId'], segmentId=identity['segmentId'],
                expectedSequence=control['controlSequence'],
                idempotencyKey='g6-b06-browser-rate', action='rate', multiple='10'))
            flow.need(code in (200, 202), 'Gui post-switch rate request failed: ' + str(rate))
            def completed():
                code, value = flow.http(8006, 'GET',
                    '/api/tasks/v3/confirmations/' + switch_key)
                flow.need(code == 200, 'Gui replacement receipt disappeared')
                return value if value['status'] == 'completed' else None
            final = flow.wait('Gui replacement completion', completed, 300)
            await until(b06_inspect, lambda x: x and '完成' in x['status'], 30)
            await evaluate("document.getElementById('controlled-replanning').scrollIntoView({block:'start'})")
            shot = await client.call('Page.captureScreenshot', {'format': 'png'}, session=tab)
            (output / 'completed.png').write_bytes(base64.b64decode(shot['data']))
            result.update(status='passed', initialReview=initial, replacementReview=review,
                          pausedAtMs=paused['simulationTimeMs'], switch=final,
                          screenshotFiles=['review.png', 'completed.png'])
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
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)
            flow.core.release.save(output / 'result.json', result)
    return result


def snapshot_or_none(session):
    try:
        return live.settled_snapshot(session)
    except (ValueError, RuntimeError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(verify(args.output.resolve(), args.session.resolve()))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
