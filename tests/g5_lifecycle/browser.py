"""Observe a real G5 page through recovery, refresh and resource service loss."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import urlopen

from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('g5_browser_base', ROOT/'tests/g5_entities/browser.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, default=str), encoding='utf-8')
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt==19:raise
            time.sleep(.02)


EXPRESSION = """(()=>{
  const b=window.__g5State?.inspect(), e=window.__g5Entities?.inspect(),
    m=window.__g5Missions?.inspect(), c=window.__g5Coverage?.inspect();
  if(!b)return {loaded:false};
  return {loaded:true,phase:b.phase,identity:b.identity,attempts:b.attempts,
    pageOrigin:performance.timeOrigin,
    snapshots:b.snapshots,deltas:b.deltas,closeCode:b.closeCode,error:b.error,
    simulationTime:b.state.simulation?.simulation_time_ms??null,lastKnownTime:b.lastKnownTime,
    counts:Object.fromEntries(['entities','tasks','routes','commands','zones'].map(k=>[k,Object.keys(b.state[k]).length])),
    completed:Object.keys(b.state.tasks).filter(k=>b.state.tasks[k].backend_completed),
    entityObjects:e?.count??null,missionObjects:m?.renderedObjects??null,
    currentObjects:c?.currentObjects??null,accumulatedObjects:c?.accumulatedObjects??null,
    coverageRunId:c?.snapshot?.runId??null,coverageStates:c?.snapshot?.sampledStates??null,
    coverageTasks:c?.snapshot?.tasks?.map(t=>t.taskId)??null,
    currentSensors:c?.sensors?Object.keys(c.sensors):null,
    timeText:document.getElementById('backend-time')?.textContent??'',
    viewerDestroyed:window.__g5Map?.viewer?.isDestroyed()??null,
    imageSource:document.querySelector('#imagery-source')?.textContent??null,
    errors:[...document.querySelectorAll('[role=alert]')].map(x=>x.textContent).filter(Boolean)};
})()"""


async def run(directory, url):
    directory = directory.resolve()
    directory.mkdir(parents=True)
    edge = Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    profile = (directory/'profile').resolve()
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(('127.0.0.1', 9223))
    args = [str(edge),'--headless=new','--no-first-run','--no-default-browser-check',
            '--disable-background-networking','--disable-background-mode','--disable-extensions',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
            '--remote-debugging-address=127.0.0.1','--remote-debugging-port=9223',
            '--window-size=1440,1100','--user-data-dir='+str(profile),'about:blank']
    process = None
    ws = None
    cdp = None
    result = dict(status='running', profile=str(profile), forcedTermination=False)
    trace = []
    with (directory/'stdout.log').open('wb') as stdout, (directory/'stderr.log').open('wb') as stderr:
        try:
            process = subprocess.Popen(args, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
            version = None
            deadline = time.monotonic()+25
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError('Edge exited before CDP was ready')
                try:
                    with urlopen('http://127.0.0.1:9223/json/version', timeout=.5) as response: version=json.load(response)
                    break
                except OSError: await asyncio.sleep(.1)
            if not version: raise RuntimeError('Edge CDP timeout')
            ws = await connect(version['webSocketDebuggerUrl'], max_size=64*1024*1024)
            cdp = base.DevTools(ws)
            target = await cdp.call('Target.createTarget', {'url':'about:blank'})
            session = (await cdp.call('Target.attachToTarget', {'targetId':target['targetId'],'flatten':True}))['sessionId']
            for method in ('Page.enable','Runtime.enable','Network.enable'): await cdp.call(method,session=session)
            await cdp.call('Page.navigate',{'url':url},session)
            async def evaluate(current_session=session, expression=EXPRESSION):
                value=await cdp.call('Runtime.evaluate',{'expression':expression,'returnByValue':True},current_session)
                if value.get('exceptionDetails'): raise RuntimeError(str(value['exceptionDetails']))
                return value.get('result',{}).get('value') or {'loaded':False}
            command_number=0
            deadline=time.monotonic()+900
            opened=False
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError('Edge exited during recovery observation')
                try: state=await evaluate()
                except Exception as error:
                    # A page reload destroys the previous execution context briefly.
                    state={'loaded':False,'reloadError':str(error)}
                state['wallTimeMs']=time.time_ns()//1000000
                if state.get('loaded') and state.get('attempts',0)>0 and not opened:
                    (directory/'opened').touch();opened=True
                save(directory/'status.json',state)
                key=lambda s:(s.get('phase'),(s.get('identity') or {}).get('run_id'),(s.get('identity') or {}).get('stream_id'),
                              s.get('counts'),s.get('completed'),s.get('coverageRunId'),s.get('coverageTasks'))
                if not trace or key(state)!=key(trace[-1]):
                    trace.append(state)
                command=directory/'commands'/f'{command_number:03d}.json'
                if command.exists():
                    request=json.loads(command.read_text(encoding='utf-8'))
                    action=request['action']
                    if action=='refresh':
                        await cdp.call('Page.reload',{'ignoreCache':True},session)
                    elif action=='capture':
                        full=await evaluate(session,'({business:window.__g5State?.inspect(),entities:window.__g5Entities?.inspect(),missions:window.__g5Missions?.inspect(),coverage:window.__g5Coverage?.inspect()})')
                        save(directory/f'capture-{command_number:03d}.json',{'summary':state,**full})
                    elif action=='late-join':
                        late_target=await cdp.call('Target.createTarget',{'url':'about:blank'})
                        late_session=(await cdp.call('Target.attachToTarget',{'targetId':late_target['targetId'],'flatten':True}))['sessionId']
                        for method in ('Page.enable','Runtime.enable','Network.enable'):await cdp.call(method,session=late_session)
                        await cdp.call('Page.navigate',{'url':url},late_session)
                        limit=time.monotonic()+50
                        while time.monotonic()<limit:
                            try: joined=await evaluate(late_session)
                            except Exception: joined={'loaded':False}
                            if joined.get('phase')=='live' and joined.get('coverageRunId'):break
                            await asyncio.sleep(.25)
                        else:raise RuntimeError('Late join did not restore a complete page')
                        save(directory/f'late-{command_number:03d}.json',joined)
                        await cdp.call('Target.closeTarget',{'targetId':late_target['targetId']})
                    elif action=='imagery-failure':
                        await evaluate(session,'(()=>{const e=document.getElementById("base-layer");e.value="satellite";e.dispatchEvent(new Event("change"));return true})()')
                        limit=time.monotonic()+18
                        while time.monotonic()<limit:
                            await asyncio.sleep(.3)
                            selected=await evaluate(session,'document.getElementById("base-layer")?.value')
                            if selected=='local':break
                        else:raise RuntimeError('Unavailable online imagery did not fall back to local map')
                    elif action=='stop':
                        save(directory/'responses'/f'{command_number:03d}.json',{'action':action,'status':'passed'})
                        break
                    else: raise RuntimeError('Unknown browser command: '+action)
                    save(directory/'responses'/f'{command_number:03d}.json',{'action':action,'status':'passed'})
                    command_number+=1
                await asyncio.sleep(.25)
            else: raise RuntimeError('Browser control timeout')
            if not opened: raise RuntimeError('Page never connected')
            if any(e['method']=='Network.webSocketFrameSent' for e in cdp.events):
                raise RuntimeError('Browser sent a business WebSocket frame')
            result.update(status='passed',browser=version['Browser'],observations=len(trace),
                          receivedFrames=sum(e['method']=='Network.webSocketFrameReceived' for e in cdp.events))
        except BaseException as error:
            result.update(status='failed',error=str(error))
            raise
        finally:
            save(directory/'trace.json',trace)
            if cdp:
                try: await cdp.call('Browser.close')
                except Exception: pass
            if ws: await ws.close()
            if process:
                try:
                    process.wait(timeout=30)
                    result['exitCode']=process.returncode
                except subprocess.TimeoutExpired:
                    process.kill();process.wait();result.update(forcedTermination=True,status='failed')
                if process.returncode!=0: result['status']='failed'
            save(directory/'result.json',result)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--url',required=True)
    args=parser.parse_args()
    asyncio.run(run(args.output,args.url))
