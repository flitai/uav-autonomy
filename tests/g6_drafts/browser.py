"""Real Edge exercises G6-B03 map drawing, editing, persistence and preview."""
import argparse
import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import traceback
from urllib.request import urlopen
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('g6_b03_cdp', ROOT / 'tests/g5_entities/browser.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)


async def verify(output):
    output.mkdir(parents=True, exist_ok=False)
    edge = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft/Edge/Application/msedge.exe'
    with socket.socket() as port:
        port.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        port.bind(('127.0.0.1', 9224))
    arguments = [str(edge), '--headless=new', '--no-first-run', '--no-default-browser-check',
                 '--disable-background-networking', '--disable-background-mode', '--disable-extensions',
                 '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
                 '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9224',
                 '--window-size=1440,1100', '--user-data-dir=' + str(output / 'profile'), 'about:blank']
    result = dict(task='G6-B03',status='running',browser='Microsoft Edge',steps=[])
    process = ws = cdp = None
    with (output / 'stdout.log').open('wb') as stdout, (output / 'stderr.log').open('wb') as stderr:
        try:
            process = subprocess.Popen(arguments,stdout=stdout,stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 25
            version = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Edge exited before CDP startup')
                try:
                    with urlopen('http://127.0.0.1:9224/json/version',timeout=.5) as response:
                        version = json.load(response)
                    break
                except Exception:
                    await asyncio.sleep(.1)
            if not version:
                raise RuntimeError('Edge CDP unavailable')
            ws = await connect(version['webSocketDebuggerUrl'],max_size=32*1024*1024)
            cdp = previous.DevTools(ws)
            target = await cdp.call('Target.createTarget',{'url':'about:blank'})
            session = (await cdp.call('Target.attachToTarget',
                {'targetId':target['targetId'],'flatten':True}))['sessionId']
            for method in ('Page.enable','Runtime.enable','Network.enable'):
                await cdp.call(method,session=session)
            await cdp.call('Page.navigate',{'url':'http://127.0.0.1:8080/'},session=session)

            async def evaluate(expression):
                answer = await cdp.call('Runtime.evaluate',
                    {'expression':expression,'returnByValue':True,'awaitPromise':True},session=session)
                if answer.get('exceptionDetails'):
                    raise RuntimeError('Browser expression failed: '+str(answer['exceptionDetails']))
                return answer.get('result',{}).get('value')

            async def until(expression,predicate,seconds=30):
                deadline = time.monotonic() + seconds
                last = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError('Edge exited during B03 interaction')
                    last = await evaluate(expression)
                    if predicate(last):
                        return last
                    await asyncio.sleep(.15)
                raise RuntimeError('Browser timeout: '+expression+' last='+str(last)[:1000])

            state = "window.__g6Tasks?.inspect()"
            initial = await until(state,lambda v:v and v['ready'] and
                                  len(v['items'])==0 and document_ready(v),60)
            result['steps'].append(dict(action='initial',state=initial))

            async def field(name,value):
                script = ("(()=>{const e=document.getElementById("+json.dumps(name)+");e.value="+
                          json.dumps(value)+";e.dispatchEvent(new Event('input',{bubbles:true}));return e.value;})()")
                return await evaluate(script)

            async def click(name):
                return await evaluate("document.getElementById("+json.dumps(name)+").click()")

            await field('task-longitude','-120.7635')
            await field('task-latitude','45.323')
            await click('task-save')
            created = await until(state,lambda v:v and len(v['items'])==1 and
                                  v['selected'] and not v['dirty'],20)
            point = created['items'][0]['draft']
            if (point['geometry']['coordinates'] != [-120.7635,45.323] or
                    point['candidateEntityIds'] != ['500']):
                raise RuntimeError('Browser point input differs from saved draft')
            result['steps'].append(dict(action='save-point',draftId=point['draftId'],
                                        revision=point['revision']))
            await click('task-preview')
            preview = await until(state,lambda v:v and v['items'][0]['planId'] and
                                  v['previewVisible'] and '未下发' in (v['result'] or ''),35)
            result['steps'].append(dict(action='preview-point',planId=preview['items'][0]['planId']))
            await click('task-copy')
            copied = await until(state,lambda v:v and len(v['items'])==2 and
                                 v['selected'] and v['selected']!=point['draftId'],15)
            result['steps'].append(dict(action='copy',draftId=copied['selected']))
            await click('task-delete')
            removed = await until(state,lambda v:v and len(v['items'])==1 and not v['selected'],15)
            result['steps'].append(dict(action='delete-copy',items=len(removed['items'])))

            await evaluate("(()=>{const e=document.getElementById('task-kind');e.value='line';e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            await click('task-draw')
            for x,y in ((720,570),(735,575)):
                for event in ('mousePressed','mouseReleased'):
                    await cdp.call('Input.dispatchMouseEvent',
                        {'type':event,'x':x,'y':y,'button':'left','clickCount':1},session=session)
            drawn = await until("document.getElementById('task-line').value",
                                lambda v:isinstance(v,str) and len(v.strip().splitlines())==2,10)
            result['steps'].append(dict(action='draw-line',coordinates=drawn))
            await click('task-save')
            line = await until(state,lambda v:v and len(v['items'])==2 and
                               any(i['draft']['kind']=='line' for i in v['items']),20)
            result['steps'].append(dict(action='save-line',items=len(line['items'])))

            await evaluate("(()=>{const e=document.getElementById('task-kind');e.value='area';e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            await field('task-longitude','-120.5645')
            await field('task-latitude','45.323')
            await field('task-width','1000')
            await field('task-height','500')
            await click('task-save')
            area = await until(state,lambda v:v and len(v['items'])==3 and
                               any(i['draft']['kind']=='area' for i in v['items']),20)
            result['steps'].append(dict(action='save-area',items=len(area['items'])))

            await cdp.call('Page.reload',{'ignoreCache':True},session=session)
            restored = await until(state,lambda v:v and v['ready'] and len(v['items'])==3,45)
            selector = ("Array.from(document.querySelectorAll('#task-drafts button')).find(b=>b.dataset.draftId==="+
                        json.dumps(point['draftId'])+")")
            await until(selector+"?.dataset.draftId",lambda v:v==point['draftId'],10)
            await evaluate(selector+".click()")
            selected = await until(state,lambda v:v and v['selected']==point['draftId'] and
                                   v['previewVisible'] and any(i['draft']['draftId']==point['draftId'] and
                                   i['planId']==preview['items'][0]['planId'] for i in v['items']),20)
            result['steps'].append(dict(action='refresh-restored',items=len(restored['items']),
                                        planId=preview['items'][0]['planId']))
            screenshot = await cdp.call('Page.captureScreenshot',{'format':'png'},session=session)
            (output / 'tasks.png').write_bytes(base64.b64decode(screenshot['data']))
            result['status']='passed'
        except Exception as error:
            result.update(status='failed',error=str(error),traceback=traceback.format_exc())
        finally:
            if cdp is not None:
                try:
                    await cdp.call('Browser.close')
                except Exception:
                    pass
            if ws is not None:
                await ws.close()
            if process is not None:
                try:
                    process.wait(timeout=30)
                    result.update(exitCode=process.returncode,forcedTermination=False)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait()
                    result.update(status='failed',forcedTermination=True)
            (output / 'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def document_ready(value):
    return bool(value and value['ready'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = asyncio.run(verify(args.output.resolve()))
    print('G6_B03_BROWSER='+result['status'],flush=True)
    return 0 if result['status']=='passed' and result.get('exitCode')==0 else 1


if __name__=='__main__':
    raise SystemExit(main())
