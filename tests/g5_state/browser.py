"""Independent real Edge/WS replay and stable gateway-snapshot comparison."""
import argparse
import asyncio
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen
from websockets.asyncio.client import connect

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/g5_environment'))
from browser import DevTools

def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def get(path):
    try:response=urlopen('http://127.0.0.1:8000'+path,timeout=3)
    except HTTPError as error:response=error
    with response:return response.status,json.load(response)

def replay(events,session,observed):
    """Independent dictionaries, replay exactly the frame boundary seen by the page."""
    streams={};matched=None;frames=[]
    target=observed['identity'];assert target
    for event in events:
        if event.get('sessionId')!=session or event['method']!='Network.webSocketFrameReceived':continue
        p=event['params'];response=p['response']
        if response['opcode']!=1:continue
        row=json.loads(response['payloadData']);frames.append(row);key=p['requestId']
        if row['kind']=='health':continue
        if row['kind']=='snapshot':
            assert key not in streams,'Repeated snapshot on same connection'
            streams[key]=deepcopy(row)
        else:
            assert key in streams,'Delta before snapshot';current=streams[key]
            assert (row['run_id'],row['stream_id'])==(current['run_id'],current['stream_id'])
            assert int(row['sequence'])==int(current['sequence'])+1
            for change in row['changes']:
                group=change['collection']
                if group=='simulation':current['state']['simulation']=deepcopy(change['value'])
                elif change['op']=='delete':current['state'][group].pop(change['id'],None)
                else:current['state'][group][change['id']]=deepcopy(change['value'])
            current['sequence']=row['sequence']
        current=streams[key]
        if all(current[k]==target[k] for k in ('run_id','stream_id','sequence')):matched=deepcopy(current)
    assert matched and matched['state']==observed['state'],'Independent frame replay differs'
    return dict(status='passed',frames=len(frames),connections=len(streams),boundary=target)

async def verify(url,directory):
    directory=directory.resolve();directory.mkdir(parents=True)
    edge=Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    with socket.socket() as probe:probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);probe.bind(('127.0.0.1',9223))
    args=[str(edge),'--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-background-mode','--disable-extensions',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost','--remote-debugging-address=127.0.0.1','--remote-debugging-port=9223',
        '--window-size=1440,1000','--user-data-dir='+str(directory/'profile'),'about:blank']
    result=dict(status='running',realGateway=True,offlineMap=True);cdp=ws=None;process=None;sessions=[]
    with (directory/'stdout.log').open('wb') as stdout,(directory/'stderr.log').open('wb') as stderr:
        try:
            process=subprocess.Popen(args,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+25;version=None
            while time.monotonic()<deadline:
                assert process.poll() is None,'Edge exited'
                try:
                    with urlopen('http://127.0.0.1:9223/json/version',timeout=.5) as response:version=json.load(response)
                    break
                except OSError:await asyncio.sleep(.1)
            assert version;ws=await connect(version['webSocketDebuggerUrl'],max_size=32*1024*1024);cdp=DevTools(ws)
            async def evaluate(session,expression):
                value=await cdp.call('Runtime.evaluate',dict(expression=expression,returnByValue=True,awaitPromise=True),session)
                assert not value.get('exceptionDetails'),value
                return value.get('result',{}).get('value')
            expression="(()=>{const m=window.__g5Map,gl=m?.viewer.scene.context._gl,e=gl?.getExtension('WEBGL_debug_renderer_info');return {business:window.__g5State?.inspect(),map:document.documentElement.dataset.ready,mapErrors:m?.errors,tilesLoaded:m?.viewer.scene.globe.tilesLoaded,timeOrigin:performance.timeOrigin,text:document.querySelector('#backend-time')?.textContent,status:document.querySelector('#backend-status')?.textContent,renderer:e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):null}})()"
            async def until(session,predicate,seconds=90):
                deadline=time.monotonic()+seconds;last=None
                while time.monotonic()<deadline:
                    assert not (directory/'request-stop').exists(),'Controller requested cleanup'
                    last=await evaluate(session,expression)
                    if predicate(last):return last
                    await asyncio.sleep(.2)
                save(directory/'timeout-state.json',last)
                raise AssertionError('Browser state timeout: '+json.dumps({k:v for k,v in last.items() if k!='business'},ensure_ascii=False))
            async def page():
                target=await cdp.call('Target.createTarget',{'url':'about:blank'})
                session=(await cdp.call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True}))['sessionId'];sessions.append(session)
                for method in ('Page.enable','Runtime.enable','Network.enable'):await cdp.call(method,session=session)
                await cdp.call('Page.bringToFront',session=session)
                await cdp.call('Page.navigate',{'url':url},session);return session
            first=await page()
            before=await until(first,lambda s:s.get('business') and s['business']['attempts']>0,30)
            assert before['business']['phase']!='live','Backend should not yet be started'
            result['beforeBackend']=before;(directory/'opened').touch()
            initial=await until(first,lambda s:s.get('map')=='true' and s.get('business',{}).get('phase')=='live' and s['business']['deltas']>=8,140)
            assert set(initial['business']['state']['entities'])=={'400','500','600'}
            result['initial']=initial;result['initialReplay']=replay(cdp.events,first,initial['business'])
            late=await page();late_state=await until(late,lambda s:s.get('map')=='true' and s.get('business',{}).get('phase')=='live' and s['business']['deltas']>=5)
            assert late_state['business']['identity']['run_id']==initial['business']['identity']['run_id']
            result['late']=late_state;result['lateReplay']=replay(cdp.events,late,late_state['business'])
            await cdp.call('Page.bringToFront',session=first)
            await cdp.call('Page.reload',{'ignoreCache':True},first)
            refreshed=await until(first,lambda s:s['timeOrigin']!=initial['timeOrigin'] and s.get('map')=='true' and s.get('business',{}).get('phase')=='live' and s['business']['deltas']>=5)
            assert refreshed['business']['snapshots']==1
            result['refresh']=refreshed;result['refreshReplay']=replay(cdp.events,first,refreshed['business'])
            (directory/'request-pause').touch()
            for session,label in ((first,'pausedFirst'),(late,'pausedLate')):
                await cdp.call('Page.bringToFront',session=session)
                paused=await until(session,lambda s:s.get('map')=='true' and s.get('tilesLoaded') and not s.get('mapErrors') and s.get('business',{}).get('phase')=='live' and s['business']['state']['simulation'].get('state')==2)
                # Let committed health and WS delivery settle; no wall-time clock prediction is permitted.
                await asyncio.sleep(1.5)
                paused=await evaluate(session,expression);status,snapshot=get('/api/v1/snapshot')
                assert status==200 and paused['business']['state']==snapshot['state']
                assert all(paused['business']['identity'][k]==snapshot[k] for k in ('run_id','stream_id','sequence'))
                result[label]=paused;result[label+'Replay']=replay(cdp.events,session,paused['business'])
                frozen=paused['business']['state']['simulation'];await asyncio.sleep(1)
                assert (await evaluate(session,expression))['business']['state']['simulation']==frozen
                for n in paused['business']['sampleCounts'].values():assert n<=2048
            await cdp.call('Page.bringToFront',session=first)
            snapshot_image=await cdp.call('Page.captureScreenshot',{'format':'png'},first)
            (directory/'real-paused.png').write_bytes(base64.b64decode(snapshot_image['data']))
            result['stableGatewaySnapshot']=snapshot;(directory/'verified').touch()
            deadline=time.monotonic()+45
            while not (directory/'gateway-stopped').exists():
                assert time.monotonic()<deadline and not (directory/'request-stop').exists();await asyncio.sleep(.1)
            for session,label in ((first,'offlineFirst'),(late,'offlineLate')):
                value=await until(session,lambda s:s.get('business') and s['business']['phase']!='live' and s['business']['identity'] is None,15)
                assert not value['business']['state']['entities'] and not value['business']['sampleCounts']
                result[label]=value
            assert not [e for e in cdp.events if e['method']=='Network.webSocketFrameSent'],'Browser sent application data'
            assert not [e for e in cdp.events if e['method']=='Runtime.exceptionThrown'],'Uncaught browser error'
            responses=[e['params']['response'] for e in cdp.events if e['method']=='Network.responseReceived']
            assert any(r['status']==503 and '/api/v1/health' in r['url'] for r in responses),'Real 503 missing'
            assert not any('/api/v1/snapshot' in r['url'] for r in responses),'Browser stitched HTTP snapshot'
            result.update(status='passed',browser=version['Browser'],readOnly=True)
        except BaseException as error:result.update(status='failed',error=str(error));raise
        finally:
            if cdp:
                save(directory/'network-events.json',cdp.events)
                try:await cdp.call('Browser.close')
                except Exception:pass
            if ws:await ws.close()
            if process:
                try:process.wait(timeout=30);result.update(exitCode=process.returncode,forcedTermination=False)
                except subprocess.TimeoutExpired:process.kill();process.wait();result.update(status='failed',forcedTermination=True)
                if process.returncode!=0:result['status']='failed'
            save(directory/'result.json',result)
    assert result['status']=='passed'

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    asyncio.run(verify(args.url,args.output))
