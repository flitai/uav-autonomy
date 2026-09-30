"""Drive the B05 sequential workflow in real Edge against a Gui session."""
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
                        ('flow', 'tests/g6_assignment/flow.py')):
    spec = importlib.util.spec_from_file_location('g6_b05_' + label, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    globals()[label] = module


async def verify(output, session):
    output.mkdir(parents=True, exist_ok=False)
    result = dict(task='G6-B05', mode='Gui', status='running', browser='Microsoft Edge',
                  steps=[])
    process = ws = client = None
    edge = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft/Edge/Application/msedge.exe'
    argv = [str(edge), '--headless=new', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-background-mode',
            '--disable-extensions',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9226',
            '--window-size=1920,1080', '--user-data-dir=' + str(output / 'profile'),
            'about:blank']
    with (output / 'stdout.log').open('wb') as stdout, \
         (output / 'stderr.log').open('wb') as stderr:
        try:
            code, state = flow.http(8005, 'GET', '/api/tasks/v2/state')
            flow.need(code == 200 and state['identity']['runId'] == session.parent.parent.name,
                      'Gui B05 session identity differs')
            identity = state['identity']
            samples = ROOT / 'out/runs/g6-b01-baseline-20260924-2223/samples'
            geometry = {
                'line': dict(type='LineString',
                             coordinates=[[-120.9923,45.3171],[-120.98,45.3171]]),
                'point': dict(type='Point', coordinates=[-120.977,45.323]),
                'area': dict(type='Rectangle', center=[-120.974,45.325],
                             widthMeters=500,heightMeters=300,rotationDegrees=0)}
            for kind in ('line','point','area'):
                sample = flow.core.release.load(samples / (kind + '-draft.json'))
                body = dict(identity, idempotencyKey='g6-b05-gui-create-' + kind,
                            kind=kind, geometry=geometry[kind],
                            candidateEntityIds=sample['candidateEntityIds'],
                            altitudeDatum='EPSG:5773')
                code, created = flow.http(8003, 'POST', '/api/tasks/v1/drafts', body)
                flow.need(code in (200,201) and created['status'] == 'confirmed',
                          'Gui draft create failed: '+str(created))
            process = subprocess.Popen(argv, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 25
            version = None
            while time.monotonic() < deadline:
                flow.need(process.poll() is None, 'Edge exited before CDP startup')
                try:
                    with urlopen('http://127.0.0.1:9226/json/version', timeout=.5) as response:
                        version = json.load(response)
                    break
                except Exception:
                    await asyncio.sleep(.1)
            flow.need(version is not None, 'Edge CDP unavailable')
            ws = await connect(version['webSocketDebuggerUrl'], max_size=32*1024*1024)
            client = cdp.DevTools(ws)
            target = await client.call('Target.createTarget', {'url':'about:blank'})
            tab = (await client.call('Target.attachToTarget',
                    {'targetId':target['targetId'],'flatten':True}))['sessionId']
            for method in ('Page.enable','Runtime.enable','Network.enable'):
                await client.call(method, session=tab)
            await client.call('Page.navigate', {'url':'http://127.0.0.1:8080/'}, session=tab)

            async def evaluate(expression):
                answer = await client.call('Runtime.evaluate',
                    {'expression':expression,'returnByValue':True,'awaitPromise':True},
                    session=tab)
                if answer.get('exceptionDetails'):
                    raise RuntimeError('Browser expression failed: '+str(answer['exceptionDetails']))
                return answer.get('result',{}).get('value')

            async def until(expression, predicate, seconds=50):
                deadline = time.monotonic() + seconds
                last = None
                while time.monotonic() < deadline:
                    flow.need(process.poll() is None, 'Edge exited during B05 interaction')
                    last = await evaluate(expression)
                    if predicate(last):
                        return last
                    await asyncio.sleep(.2)
                raise TimeoutError('Browser timeout: '+expression+' last='+str(last)[:300])

            inspect = 'window.__g6Assignment?.inspect()'
            await until(inspect, lambda x:x and x['state'] and len(x['state']['drafts'])==3, 70)
            await evaluate("document.getElementById('multi-task-planning').open=true")
            await evaluate("(()=>{const e=document.getElementById('multi-relationship');"
                           "e.value='sequence';e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            selected = await evaluate("(()=>({count:document.querySelectorAll('.multi-task-card').length,"
                "previewDisabled:document.getElementById('multi-preview').disabled,"
                "candidates:[...document.querySelectorAll('.multi-candidates input')].map(x=>"
                "({checked:x.checked,disabled:x.disabled}))}))()")
            flow.need(selected['count']==3 and not selected['previewDisabled'] and
                      all(x['disabled'] for x in selected['candidates']),
                      'Sequential candidate selector did not limit qualification')
            result['steps'].append(dict(action='choose-sequence', selection=selected))
            await evaluate("document.getElementById('multi-preview').click()")
            planned = await until(inspect, lambda x:x and x['review'] and
                                  x['review']['planId'], 70)
            review = planned['review']
            flow.need(review['relationship']=='sequence' and review['confirmationAllowed'] and
                      len(review['plan']['assignments'])==3 and
                      {x['vehicleId'] for x in review['plan']['assignments']}=={'400'},
                      'Browser review did not show the qualified serial plan')
            flow.need(await evaluate("document.getElementById('multi-confirm').disabled"),
                      'Unacknowledged multi-task plan could be submitted')
            result['review'] = review
            await evaluate("document.getElementById('multi-task-planning').scrollIntoView({block:'start'})")
            shot = await client.call('Page.captureScreenshot', {'format':'png'}, session=tab)
            (output / 'review.png').write_bytes(base64.b64decode(shot['data']))
            await evaluate("(()=>{const e=document.getElementById('multi-ack');e.checked=true;"
                           "e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            flow.need(not await evaluate("document.getElementById('multi-confirm').disabled"),
                      'Acknowledged plan remained disabled')
            await evaluate("document.getElementById('multi-confirm').click()")
            confirmed = await until(inspect, lambda x:x and x['confirmationKey'] and
                                    not x['status'].startswith('正在确认'), 70)
            key = confirmed['confirmationKey']
            code, receipt = flow.http(8005, 'GET', '/api/tasks/v2/confirmations/'+key)
            flow.need(code==200 and receipt['status'] in ('confirmed','executing','completed'),
                      'Browser confirmation did not reach active UxAS')
            result['steps'].append(dict(action='confirm',key=key,phase=receipt['phase']))
            control = flow.http(8001, 'GET', '/api/control/v1/state')[1]
            code, rate = flow.http(8001, 'POST', '/api/control/v1/operations', dict(
                runId=identity['runId'],segmentId=identity['segmentId'],
                expectedSequence=control['controlSequence'],idempotencyKey='g6-b05-gui-rate',
                action='rate',multiple='10'))
            flow.need(code in (200,202) and rate['status'] in ('pending','applied','confirmed'),
                      'Gui rate operation failed')

            def completed():
                code, row = flow.http(8005,'GET','/api/tasks/v2/confirmations/'+key)
                flow.need(code==200, 'Gui confirmation became unavailable')
                return row if row['status']=='completed' else None
            receipt = flow.wait('Gui task completion', completed, 300)
            result['audit'] = flow.audit(session,review,receipt,'sequence')
            result['receipt'] = receipt
            result['steps'].append(dict(action='complete',tasks=len(receipt['tasks'])))
            await evaluate("document.getElementById('multi-task-planning').scrollIntoView({block:'start'})")
            shot = await client.call('Page.captureScreenshot', {'format':'png'}, session=tab)
            (output / 'completed.png').write_bytes(base64.b64decode(shot['data']))
            result['status']='passed'
        except Exception as error:
            result.update(status='failed',error=str(error),traceback=traceback.format_exc())
            print(result['traceback'],file=sys.stderr)
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
                    result['edgeForcedTermination']=True
                result['edgeExitCode']=process.returncode
            (output / 'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',
                                                encoding='utf-8')
    return 0 if result['status']=='passed' else 1


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--session',type=Path,required=True)
    args=parser.parse_args()
    return asyncio.run(verify(args.output.resolve(),args.session.resolve()))


if __name__=='__main__':
    sys.exit(main())
