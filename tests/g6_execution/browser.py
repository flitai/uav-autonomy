"""Real Edge review and explicit confirmation of the saved B04 plan."""
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

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('g6_b04_cdp',ROOT/'tests/g5_entities/browser.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

async def verify(output):
    output.mkdir(parents=True,exist_ok=False)
    edge=Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    args=[str(edge),'--headless=new','--no-first-run','--no-default-browser-check',
          '--disable-background-networking','--disable-background-mode','--disable-extensions',
          '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
          '--remote-debugging-address=127.0.0.1','--remote-debugging-port=9224',
          '--window-size=1600,1100','--user-data-dir='+str(output/'profile'),'about:blank']
    result=dict(task='G6-B04',status='running',browser='Microsoft Edge',steps=[])
    process=ws=cdp=None
    with (output/'stdout.log').open('wb') as stdout,(output/'stderr.log').open('wb') as stderr:
        try:
            process=subprocess.Popen(args,stdout=stdout,stderr=stderr,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+25;version=None
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Edge exited before CDP startup')
                try:
                    with urlopen('http://127.0.0.1:9224/json/version',timeout=.5) as response:
                        version=json.load(response)
                    break
                except Exception:await asyncio.sleep(.1)
            if not version:raise TimeoutError('Edge CDP unavailable')
            ws=await connect(version['webSocketDebuggerUrl'],max_size=32*1024*1024)
            cdp=previous.DevTools(ws)
            target=await cdp.call('Target.createTarget',{'url':'about:blank'})
            session=(await cdp.call('Target.attachToTarget',
                     {'targetId':target['targetId'],'flatten':True}))['sessionId']
            for method in ('Page.enable','Runtime.enable','Network.enable'):
                await cdp.call(method,session=session)
            await cdp.call('Page.navigate',{'url':'http://127.0.0.1:8080/'},session=session)

            async def evaluate(expression):
                answer=await cdp.call('Runtime.evaluate',
                    {'expression':expression,'returnByValue':True,'awaitPromise':True},session=session)
                if answer.get('exceptionDetails'):
                    raise RuntimeError('Browser expression failed: '+str(answer['exceptionDetails']))
                return answer.get('result',{}).get('value')

            async def until(expression,predicate,seconds=50):
                deadline=time.monotonic()+seconds;last=None
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError('Edge exited during B04 interaction')
                    last=await evaluate(expression)
                    if predicate(last):return last
                    await asyncio.sleep(.15)
                raise TimeoutError('Browser timeout: '+expression+' last='+str(last)[:500])

            task='window.__g6Tasks?.inspect()';execution='window.__g6Execution?.inspect()'
            await until('Boolean(window.__g6Execution&&window.__g6Tasks?.inspect().ready)',bool,70)
            def field(name,value):
                return ("(()=>{const e=document.getElementById("+json.dumps(name)+");e.value="+
                        json.dumps(value)+";e.dispatchEvent(new Event('input',{bubbles:true}));return e.value;})()")
            await evaluate("(()=>{const e=document.getElementById('task-kind');e.value='line';e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            await evaluate(field('task-line','-120.9923, 45.3171\n-120.9800, 45.3171'))
            await evaluate("(()=>{const e=document.getElementById('task-entity');e.value='400';e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            await evaluate("document.getElementById('task-save').click()")
            saved=await until(task,lambda v:v and len(v['items'])==1 and not v['dirty'])
            result['steps'].append(dict(action='save',draftId=saved['items'][0]['draft']['draftId']))
            await evaluate("document.getElementById('task-preview').click()")
            preview=await until(task,lambda v:v and v['items'][0]['planId'],45)
            plan_id=preview['items'][0]['planId']
            result['steps'].append(dict(action='preview',planId=plan_id))
            await until("!document.getElementById('execution-load').disabled",bool,10)
            await evaluate("document.getElementById('execution-load').click()")
            reviewed=await until(execution,lambda v:v and v['review'] and
                                 v['review']['planId']==plan_id and len(v['review']['waypoints'])>=2)
            disabled=await evaluate("document.getElementById('execution-confirm').disabled")
            if not disabled:raise RuntimeError('Unacknowledged plan could be submitted')
            count=await evaluate("document.querySelectorAll('#execution-route li').length")
            if count!=len(reviewed['review']['waypoints']):
                raise RuntimeError('Page omitted route waypoints')
            result['steps'].append(dict(action='review',digest=reviewed['review']['reviewSHA256'],
                                        waypoints=count,acknowledgementRequired=disabled))
            screenshot=await cdp.call('Page.captureScreenshot',{'format':'png'},session=session)
            (output/'review.png').write_bytes(base64.b64decode(screenshot['data']))
            await evaluate("(()=>{const e=document.getElementById('execution-ack');e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));})()")
            enabled=await evaluate("!document.getElementById('execution-confirm').disabled")
            if not enabled:raise RuntimeError('Acknowledged plan remained disabled')
            await evaluate("document.getElementById('execution-confirm').click()")
            receipt=await until(execution,lambda v:v and v['receipt'] and
                                v['receipt']['status'] in ('confirmed','completed'),70)
            result['steps'].append(dict(action='confirm',receipt=receipt['receipt']))
            result['status']='passed'
        except Exception as error:
            result.update(status='failed',error=str(error),traceback=traceback.format_exc())
        finally:
            if cdp is not None:
                try:await cdp.call('Browser.close')
                except Exception:pass
            if ws is not None:await ws.close()
            if process is not None:
                try:process.wait(timeout=12)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                result.update(exitCode=process.returncode,forcedTermination=False)
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if result['status']=='passed' else 1

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();return asyncio.run(verify(args.output.resolve()))

if __name__=='__main__':sys.exit(main())
