"""Bounded, thirty-minute real Edge/Cesium observation for G5-T10."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import urlopen

from websockets.asyncio.client import connect


class DevTools:
    def __init__(self,websocket):
        self.ws=websocket;self.sequence=0
        self.received=0;self.sent=0;self.model_requests={};self.failures=0
    async def call(self,method,params=None,session=None):
        self.sequence+=1;identity=self.sequence
        command=dict(id=identity,method=method,params=params or {})
        if session:command['sessionId']=session
        await self.ws.send(json.dumps(command))
        while True:
            response=json.loads(await asyncio.wait_for(self.ws.recv(),30))
            event=response.get('method')
            if event=='Network.webSocketFrameReceived':self.received+=1
            elif event=='Network.webSocketFrameSent':self.sent+=1
            elif event=='Network.loadingFailed':self.failures+=1
            elif event=='Network.requestWillBeSent':
                url=response.get('params',{}).get('request',{}).get('url','')
                if url.lower().split('?',1)[0].endswith(('.glb','.gltf')):
                    self.model_requests[url]=self.model_requests.get(url,0)+1
            if response.get('id')==identity:
                if 'error' in response:raise RuntimeError(str(response['error']))
                return response.get('result',{})


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,default=str),encoding='utf-8')
    for attempt in range(20):
        try:os.replace(temporary,path);return
        except PermissionError:
            if attempt==19:raise
            time.sleep(.02)


INSTALL="""(()=>{
 if(window.__g5ScaleFrames)return true;
 const samples=[],probe={samples,last:null};window.__g5ScaleFrames=probe;
 function frame(t){if(probe.last!==null){samples.push(t-probe.last);if(samples.length>3000)samples.shift()}
   probe.last=t;requestAnimationFrame(frame)}requestAnimationFrame(frame);return true;
})()"""

STATUS="""(()=>{
 const b=window.__g5State?.inspect(),e=window.__g5Entities?.inspect(),
   m=window.__g5Missions?.inspect(),c=window.__g5Coverage?.inspect(),v=window.__g5Map?.viewer;
 if(!b)return {loaded:false};
 const gl=v?.scene?.context?._gl,ext=gl?.getExtension('WEBGL_debug_renderer_info');
 const frames=(window.__g5ScaleFrames?.samples??[]).slice(-300).sort((a,b)=>a-b);
 const q=p=>frames.length?frames[Math.ceil(p*frames.length)-1]:null;
 const camera=v?.camera;
 return {loaded:true,phase:b.phase,identity:b.identity,attempts:b.attempts,
   pageOrigin:performance.timeOrigin,snapshots:b.snapshots,deltas:b.deltas,
   simulationTime:b.state.simulation?.simulation_time_ms??null,
   counts:Object.fromEntries(['entities','tasks','routes','commands','zones'].map(k=>[k,Object.keys(b.state[k]).length])),
   completed:Object.keys(b.state.tasks).filter(k=>b.state.tasks[k].backend_completed),
   entityObjects:e?.count??null,missionObjects:m?.renderedObjects??null,
   currentObjects:c?.currentObjects??null,accumulatedObjects:c?.accumulatedObjects??null,
   coverageRunId:c?.snapshot?.runId??null,coverageStates:c?.snapshot?.sampledStates??null,
   coverageTasks:c?.snapshot?.tasks?.length??null,
   renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):null,
   vendor:ext?gl.getParameter(ext.UNMASKED_VENDOR_WEBGL):null,
   canvas:v?.canvas?[v.canvas.width,v.canvas.height]:null,
   viewport:[innerWidth,innerHeight],devicePixelRatio:devicePixelRatio,
   cameraPosition:camera?[camera.positionWC.x,camera.positionWC.y,camera.positionWC.z]:null,
   cameraDirection:camera?[camera.directionWC.x,camera.directionWC.y,camera.directionWC.z]:null,
   frameSamples:frames.length,frameP50Ms:q(.5),frameP95Ms:q(.95),
   baseLayer:document.getElementById('base-layer')?.value??null,
   viewerDestroyed:v?.isDestroyed()??null,
   errors:[...document.querySelectorAll('[role=alert]')].map(x=>x.textContent).filter(Boolean)};
})()"""


async def run(directory,url):
    directory=directory.resolve();directory.mkdir(parents=True)
    edge=Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        probe.bind(('127.0.0.1',9223))
    profile=(directory/'profile').resolve()
    args=[str(edge),'--headless=new','--no-first-run','--no-default-browser-check',
          '--disable-background-networking','--disable-background-mode','--disable-extensions',
          '--enable-precise-memory-info',
          '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
          '--remote-debugging-address=127.0.0.1','--remote-debugging-port=9223',
          '--window-size=1440,1100','--user-data-dir='+str(profile),'about:blank']
    browser=None;ws=None;cdp=None;result=dict(status='running',forcedTermination=False)
    samples=[];trace=[]
    with (directory/'stdout.log').open('wb') as stdout,(directory/'stderr.log').open('wb') as stderr:
        try:
            browser=subprocess.Popen(args,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+25;version=None
            while time.monotonic()<deadline:
                if browser.poll() is not None:raise RuntimeError('Edge exited before CDP readiness')
                try:
                    with urlopen('http://127.0.0.1:9223/json/version',timeout=.5) as response:version=json.load(response)
                    break
                except OSError:await asyncio.sleep(.1)
            if not version:raise RuntimeError('Edge CDP timeout')
            ws=await connect(version['webSocketDebuggerUrl'],max_size=64*1024*1024)
            cdp=DevTools(ws)
            target=await cdp.call('Target.createTarget',{'url':'about:blank'})
            session=(await cdp.call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True}))['sessionId']
            for method in ('Page.enable','Runtime.enable','Network.enable'):await cdp.call(method,session=session)
            await cdp.call('Page.navigate',{'url':url},session)
            async def evaluate(expression):
                response=await cdp.call('Runtime.evaluate',{'expression':expression,'returnByValue':True},session)
                if response.get('exceptionDetails'):raise RuntimeError(str(response['exceptionDetails']))
                return response.get('result',{}).get('value')
            opened=False;installed=False;command_number=0;next_sample=time.monotonic()
            interactions=[]
            deadline=time.monotonic()+2650
            while time.monotonic()<deadline:
                if browser.poll() is not None:raise RuntimeError('Edge exited during long observation')
                try:status=await evaluate(STATUS) or {'loaded':False}
                except Exception as error:status={'loaded':False,'evaluationError':str(error)}
                status['wallTimeMs']=time.time_ns()//1000000
                save(directory/'status.json',status)
                if status.get('loaded') and status.get('attempts',0)>0 and not opened:
                    (directory/'opened').touch();opened=True
                if status.get('loaded') and not installed:
                    await evaluate(INSTALL);installed=True
                if (status.get('phase')=='live' and status.get('entityObjects')==20 and
                        (not interactions or len(interactions)==1 and
                         int(status.get('simulationTime') or 0)>=900000)):
                    entity='400' if not interactions else '500'
                    began=time.monotonic()
                    script="""(()=>{
                      const button=document.querySelector('#entity-list button[data-entity-id="TARGET"]');
                      if(!button)return {error:'entity list button missing'};
                      button.click();
                      const selected=window.__g5Entities?.inspect().selected;
                      const title=document.getElementById('selected-title')?.textContent;
                      const locate=document.getElementById('entity-locate');
                      if(locate?.disabled)return {error:'locate disabled',selected,title};
                      locate.click();document.getElementById('entity-reset')?.click();
                      return {selected,title,locateEnabled:true};
                    })()""".replace('TARGET',entity)
                    choice=await evaluate(script)
                    if choice.get('selected')!=entity or entity not in (choice.get('title') or '') or not choice.get('locateEnabled'):
                        raise RuntimeError('Twenty-aircraft page interaction failed: '+str(choice))
                    interactions.append(dict(entityId=entity,simulationTime=status.get('simulationTime'),
                        roundTripMilliseconds=(time.monotonic()-began)*1000,controls=choice))
                key=[status.get('phase'),(status.get('identity') or {}).get('stream_id'),
                     status.get('counts'),status.get('completed'),status.get('coverageRunId')]
                if not trace or key!=trace[-1]['key']:
                    trace.append(dict(key=key,status=status))
                    if len(trace)>512:trace.pop(0)
                if status.get('loaded') and time.monotonic()>=next_sample:
                    heap=await cdp.call('Runtime.getHeapUsage',session=session)
                    samples.append(dict(wallTimeMs=status['wallTimeMs'],simulationTime=status.get('simulationTime'),
                                        phase=status.get('phase'),frameP50Ms=status.get('frameP50Ms'),
                                        frameP95Ms=status.get('frameP95Ms'),
                                        jsHeapUsedBytes=heap.get('usedSize'),jsHeapTotalBytes=heap.get('totalSize'),
                                        entityObjects=status.get('entityObjects'),missionObjects=status.get('missionObjects'),
                                        currentObjects=status.get('currentObjects'),accumulatedObjects=status.get('accumulatedObjects')))
                    next_sample=time.monotonic()+5
                    save(directory/'samples.json',samples)
                command=directory/'commands'/f'{command_number:03d}.json'
                if command.exists():
                    action=json.loads(command.read_text(encoding='utf-8'))['action']
                    if action=='capture':
                        full=await evaluate('({business:window.__g5State?.inspect(),entities:window.__g5Entities?.inspect(),missions:window.__g5Missions?.inspect(),coverage:window.__g5Coverage?.inspect()})')
                        save(directory/f'capture-{command_number:03d}.json',dict(summary=status,**full))
                    elif action=='stop':
                        save(directory/'responses'/f'{command_number:03d}.json',dict(action=action,status='passed'))
                        break
                    else:raise RuntimeError('Unknown browser command: '+action)
                    save(directory/'responses'/f'{command_number:03d}.json',dict(action=action,status='passed'))
                    command_number+=1
                await asyncio.sleep(.5)
            else:raise RuntimeError('Long browser observation timeout')
            if not opened or not samples or len(interactions)!=2:
                raise RuntimeError('Browser did not render and handle both live interactions')
            if cdp.sent:raise RuntimeError('Browser sent a business WebSocket frame')
            result.update(status='passed',browser=version['Browser'],receivedFrames=cdp.received,
                          sentBusinessFrames=cdp.sent,modelRequests=cdp.model_requests,
                          networkFailures=cdp.failures,sampleCount=len(samples),traceCount=len(trace),
                          interactions=interactions)
        except BaseException as error:
            result.update(status='failed',error=str(error));raise
        finally:
            save(directory/'trace.json',trace)
            if cdp:
                try:await cdp.call('Browser.close')
                except Exception:pass
            if ws:await ws.close()
            if browser:
                try:browser.wait(timeout=30);result['exitCode']=browser.returncode
                except subprocess.TimeoutExpired:
                    browser.kill();browser.wait();result.update(forcedTermination=True,status='failed')
                if browser.returncode!=0:result['status']='failed'
            save(directory/'result.json',result)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--url',required=True);a=parser.parse_args()
    asyncio.run(run(a.output,a.url))
