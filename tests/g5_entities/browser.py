"""Real browser model/pose/trajectory/time checks, independent received-frame replay."""
import argparse
import asyncio
import base64
import importlib.util
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from websockets.asyncio.client import connect

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('g5_entity_state_browser',ROOT/'tests/g5_state/browser.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
save=previous.save;DevTools=previous.DevTools
spec=importlib.util.spec_from_file_location('g5_entity_screen',Path(__file__).with_name('screen.py'))
screen=importlib.util.module_from_spec(spec);spec.loader.exec_module(screen)

def ecef(p,grid):
    lon,lat=p['longitude_deg'],p['latitude_deg'];assert p['altitude_reference']==1
    x=(lon-grid['west'])/grid['stepDegrees'];y=(grid['north']-lat)/grid['stepDegrees'];col=min(grid['width']-2,int(x));row=min(grid['height']-2,int(y));fx=x-col;fy=y-row
    v=lambda dy,dx:grid['values'][(row+dy)*grid['width']+col+dx]
    n=(1-fy)*((1-fx)*v(0,0)+fx*v(0,1))+fy*((1-fx)*v(1,0)+fx*v(1,1));h=p['altitude_m']+n
    lon,lat=map(math.radians,(lon,lat));a=6378137.;f=1/298.257223563;e2=f*(2-f);normal=a/math.sqrt(1-e2*math.sin(lat)**2)
    return [(normal+h)*math.cos(lat)*math.cos(lon),(normal+h)*math.cos(lat)*math.sin(lon),(normal*(1-e2)+h)*math.sin(lat)]

def pose_check(events,session,state,grid):
    business=state['business'];previous.replay(events,session,business);target=business['identity'];samples={};found=False
    requests=[e['params']['requestId'] for e in events if e.get('sessionId')==session and e['method']=='Network.webSocketCreated']
    assert requests
    for event in events:
        if event.get('sessionId')!=session or event['method']!='Network.webSocketFrameReceived':continue
        if event['params']['requestId']!=requests[-1]:continue
        response=event['params']['response']
        if response['opcode']!=1:continue
        message=json.loads(response['payloadData'])
        if message['kind']=='health':continue
        if message['kind']=='snapshot':samples={}
        elif message['kind']=='delta':
            for change in message['changes']:
                if change['collection']=='entities':
                    if change['op']=='delete':samples.pop(change['id'],None)
                    elif change['value'].get('position'):
                        row=change['value'];items=samples.setdefault(change['id'],{})
                        items[row['simulation_time_ms']]=row
        if all(message[k]==target[k] for k in ('run_id','stream_id','sequence')):found=True;break
    assert found
    error=0;checks=[]
    for identity,pose in state['entities']['objects'].items():
        available=samples.get(identity,{})
        if not available:
            row=business['state']['entities'][identity];available={row['simulation_time_ms']:row}
        a,b=available[pose['lower']],available[pose['upper']]
        assert int(pose['lower'])<=int(pose['time'])<=int(pose['upper'])
        fraction=(int(pose['time'])-int(pose['lower']))/(int(pose['upper'])-int(pose['lower'])) if pose['lower']!=pose['upper'] else 0
        assert abs(fraction-pose['fraction'])<1e-12
        pa,pb=ecef(a['position'],grid),ecef(b['position'],grid)
        expected=[x+(y-x)*fraction for x,y in zip(pa,pb)]
        distance=math.dist(expected,pose['position']);assert distance<=1;error=max(error,distance)
        checks.append(dict(entityId=identity,time=pose['time'],lower=pose['lower'],upper=pose['upper'],fraction=fraction,errorMeters=distance))
    return dict(status='passed',maximumPositionError=error,checks=checks)

EXPRESSION="""(()=>{
 const m=window.__g5Map,v=m?.viewer,models={};let visited=0;
 function walk(p){if(!p||++visited>10000)return;if(p.id?.id?.startsWith('aircraft:')&&p.modelMatrix){models[p.id.id.slice(9)]={ready:p.ready,scale:p.scale,matrix:Array.from(p.modelMatrix),axis:p._sceneGraph?Array.from(p._sceneGraph._axisCorrectionMatrix):null,textureBytes:p.statistics?.texturesByteLength,color:p.color?.toCssHexString(),colorBlendMode:p.colorBlendMode,outline:p.silhouetteColor?.toCssHexString(),outlinePixels:p.silhouetteSize,silhouetteId:p._silhouetteId,customLighting:!!p.customShader};}
 if(typeof p.get==='function'&&typeof p.length==='number')for(let i=0;i<p.length;i++)walk(p.get(i));}
 if(v)walk(v.scene.primitives);const gl=v?.scene.context._gl,e=gl?.getExtension('WEBGL_debug_renderer_info');
 return {business:window.__g5State?.inspect(),entities:window.__g5Entities?.inspect(),models,map:document.documentElement.dataset.ready,mapErrors:m?.errors,tilesLoaded:v?.scene.globe.tilesLoaded,timeOrigin:performance.timeOrigin,text:document.querySelector('#backend-time')?.textContent,detail:document.querySelector('#entity-details')?.textContent,renderer:e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):null,cameraHeight:v?.camera.positionCartographic.height};})()"""

def motion_check(frames):
    assert len(frames)>3,'No intermediate rendered frames'
    interior=0;steps=[];errors=[];brackets=set()
    for frame in frames:
        assert int(frame['lower'])<=int(frame['time'])<=int(frame['upper'])
        errors.append(math.dist(frame['position'],frame['rendered']))
        brackets.add((frame['lower'],frame['upper']))
    assert max(errors)<=1,'Rendered model lags interpolated pose'
    for a,b in zip(frames,frames[1:]):
        step=int(b['clock'])-int(a['clock']);assert step>=0;steps.append(step)
        # Same received bracket, distinct intermediate positions: fails the old packet-only implementation.
        if (a['lower'],a['upper'])==(b['lower'],b['upper']) and 0<a['fraction']<b['fraction']<1:
            assert math.dist(a['position'],b['position'])>0;interior+=1
        assert step<=111,'Display clock snapped by a full message interval'
    assert len(brackets)>=2 and interior>=6,(len(brackets),interior)
    return dict(status='passed',frames=len(frames),receivedBrackets=len(brackets),interiorMovingFrames=interior,
        maximumStepMilliseconds=max(steps),maximumRenderedPositionErrorMeters=max(errors),
        observedFramesPerSecond=(len(frames)-1)*1000/(frames[-1]['wall']-frames[0]['wall']))

async def verify(url,directory):
    directory=directory.resolve();directory.mkdir(parents=True)
    context=json.loads((directory.parent.parent/'context.json').read_text(encoding='utf-8'))
    service=json.loads((Path(context['entityCandidate'])/'service.json').read_text(encoding='utf-8'))
    runtime=json.loads((Path(service['dist'])/'entities/runtime.json').read_text(encoding='utf-8'));grid=runtime['height']
    edge=Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    with socket.socket() as probe:probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);probe.bind(('127.0.0.1',9223))
    args=[str(edge),'--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-background-mode','--disable-extensions',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost','--remote-debugging-address=127.0.0.1','--remote-debugging-port=9223','--window-size=1440,1100','--user-data-dir='+str(directory/'profile'),'about:blank']
    result=dict(status='running',scope='real-entity-display',offline=True);cdp=ws=process=None
    with (directory/'stdout.log').open('wb') as stdout,(directory/'stderr.log').open('wb') as stderr:
        try:
            process=subprocess.Popen(args,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+25;version=None
            while time.monotonic()<deadline:
                assert process.poll() is None
                try:
                    with urlopen('http://127.0.0.1:9223/json/version',timeout=.5) as response:version=json.load(response)
                    break
                except OSError:await asyncio.sleep(.1)
            assert version;ws=await connect(version['webSocketDebuggerUrl'],max_size=32*1024*1024);cdp=DevTools(ws)
            target=await cdp.call('Target.createTarget',{'url':'about:blank'});session=(await cdp.call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True}))['sessionId']
            for method in ('Page.enable','Runtime.enable','Network.enable'):await cdp.call(method,session=session)
            await cdp.call('Page.bringToFront',session=session)
            async def evaluate(expression):
                answer=await cdp.call('Runtime.evaluate',dict(expression=expression,returnByValue=True,awaitPromise=True),session);assert not answer.get('exceptionDetails'),answer
                return answer.get('result',{}).get('value')
            async def until(predicate,seconds=90):
                deadline=time.monotonic()+seconds;last=None
                while time.monotonic()<deadline:
                    assert not (directory/'request-stop').exists(),'Controller stopped browser'
                    last=await evaluate(EXPRESSION)
                    if predicate(last):return last
                    await asyncio.sleep(.2)
                save(directory/'timeout-state.json',last);raise AssertionError('Entity browser timeout')
            async def click(identity):await evaluate("document.getElementById("+json.dumps(identity)+").click();true")
            async def shot(name):
                image=await cdp.call('Page.captureScreenshot',{'format':'png'},session);png=base64.b64decode(image['data']);(directory/(name+'.png')).write_bytes(png);return png
            async def key(value):
                for kind in ('keyDown','keyUp'):await cdp.call('Input.dispatchKeyEvent',dict(type=kind,key=value),session)
            await cdp.call('Page.navigate',{'url':url},session)
            await until(lambda s:s.get('business') and s['business']['attempts']>0,40);(directory/'opened').touch()
            live=await until(lambda s:s.get('map')=='true' and s.get('business',{}).get('phase')=='live' and s.get('entities',{}).get('count')==3 and all(n>=5 for n in s['business']['sampleCounts'].values()) and len(s['business']['sampleCounts'])==3,150)
            assert not live['entities']['error'];result['initial']=live;result['initialPoseCheck']=pose_check(cdp.events,session,live,grid)
            await evaluate("document.querySelector('[data-entity-id=\"400\"]').click();true");await click('entity-locate')
            loaded=await until(lambda s:len(s['models'])==3 and all(m['ready'] and m['textureBytes']>0 for m in s['models'].values()) and s['models']['400'].get('outlinePixels')==3)
            assert loaded['entities']['selected']=='400' and '1090.00' in loaded['detail'];result['loaded']=loaded
            for identity,expected in [('400','#00e5ff'),('500','#00e5ff'),('600','#ff4265')]:
                assert loaded['models'][identity]['color']==expected and loaded['models'][identity]['colorBlendMode']==0
                assert loaded['models'][identity]['customLighting'] and not loaded['entities']['objects'][identity]['pointFallback']
                assert loaded['models'][identity]['outlinePixels']==(3 if identity=='400' else 2)
                assert loaded['models'][identity]['silhouetteId']>0
                assert loaded['entities']['objects'][identity]['affiliation']['source']=='display-config'
                assert loaded['business']['state']['entities'][identity]['configuration']['Affiliation']=='Unknown'
            assert '用户指定' in loaded['detail'] and '蓝方' in loaded['detail']
            for identity,model in loaded['models'].items():
                assert math.dist(model['matrix'][12:15],loaded['entities']['objects'][identity]['position'])<=1
                # Actual Cesium engine maps GLB +Z to model +X, +Y to +Z.
                assert math.dist(model['axis'][8:11],[1,0,0])<1e-12 and math.dist(model['axis'][4:7],[0,0,1])<1e-12
            await shot('real-model-running')
            motion_expression=Path(__file__).with_name('motion.js').read_text(encoding='utf-8')
            frames=await evaluate(motion_expression);save(directory/'rendered-motion.json',frames);result['motion']=motion_check(frames)
            await click('entity-follow');await until(lambda s:s['entities']['followed']=='400')
            frames=await evaluate(motion_expression);save(directory/'rendered-follow-motion.json',frames);result['followMotion']=motion_check(frames)
            assert all(f['followed']=='400' for f in frames)
            await click('entity-reset');await click('entity-locate')
            moved=await evaluate(EXPRESSION);assert math.dist(moved['entities']['objects']['400']['position'],loaded['entities']['objects']['400']['position'])>1
            result['movingPoseCheck']=pose_check(cdp.events,session,moved,grid)
            (directory/'request-pause').touch()
            paused=await until(lambda s:s.get('business',{}).get('phase')=='live' and s['business']['state']['simulation'].get('state')==2)
            await asyncio.sleep(1.5);paused=await evaluate(EXPRESSION);result['paused']=paused;result['pausedPoseCheck']=pose_check(cdp.events,session,paused,grid)
            assert all(p['trailPoints']>=2 for p in paused['entities']['objects'].values())
            await asyncio.sleep(1.2);frozen=await evaluate(EXPRESSION);assert frozen['entities']['objects']==paused['entities']['objects'] and frozen['text']==paused['text']
            await key('+');await key('+');scaled=await evaluate(EXPRESSION);assert abs(scaled['entities']['modelScale']-2)<1e-10
            scaled=await until(lambda s:all(abs(m['scale']/paused['models'][identity]['scale']-2)<1e-6 for identity,m in s['models'].items()))
            for identity,pose in scaled['entities']['objects'].items():assert pose['position']==paused['entities']['objects'][identity]['position'] and pose['orientation']==paused['entities']['objects'][identity]['orientation']
            await key('-');assert abs((await evaluate(EXPRESSION))['entities']['modelScale']-math.sqrt(2))<1e-10
            await key('0');assert (await evaluate(EXPRESSION))['entities']['modelScale']==1
            for _ in range(18):await key('+')
            assert (await evaluate(EXPRESSION))['entities']['modelScale']==runtime['display']['maximumScale']
            for _ in range(30):await key('-')
            assert (await evaluate(EXPRESSION))['entities']['modelScale']==runtime['display']['minimumScale']
            await key('0');result['scaleShortcuts']=dict(status='passed',default=1,display=runtime['display'],changesSimulation=False)
            await click('entity-follow');following=await until(lambda s:s['entities']['followed']=='400');result['following']=following
            await click('entity-reset');reset=await until(lambda s:s['entities']['followed'] is None and abs(s['cameraHeight']-45000)<2);result['reset']=reset
            for control,field in (('label-toggle','labels'),('trail-toggle','trails'),('entity-toggle','visible')):
                await click(control);assert not (await evaluate(EXPRESSION))['entities'][field];await click(control)
            await click('entity-locate');await until(lambda s:s['cameraHeight']<3000 and s['tilesLoaded']);await shot('real-model-paused')
            await click('label-toggle');await click('trail-toggle')
            measures=[]
            for name,backward in [('near',0),('medium',1840),('far',48000)]:
                await evaluate(f'window.__g5Map.viewer.camera.moveBackward({backward});window.__g5Map.viewer.scene.requestRender();true')
                await asyncio.sleep(.7)
                measurement=screen.measure(await shot('screen-size-'+name));measures.append(measurement)
                assert measurement['pixels']>300 and max(measurement['width'],measurement['height'])>35,measurement
            assert max(m['width'] for m in measures)/min(m['width'] for m in measures)<1.18,measures
            assert max(m['height'] for m in measures)/min(m['height'] for m in measures)<1.18,measures
            await key('+');await key('+');await asyncio.sleep(.7)
            enlarged=screen.measure(await shot('screen-size-enlarged'))
            assert 1.8<enlarged['width']/measures[-1]['width']<2.2,(measures,enlarged)
            assert enlarged['brightnessSpan']>=18 and enlarged['levels']>=25,enlarged
            result['screenDisplay']=dict(status='passed',distancesMeters=[160,2000,50000],measurements=measures,enlarged=enlarged,geometryLighting=True)
            await key('0');await click('label-toggle');await click('trail-toggle')
            await evaluate("document.querySelector('[data-entity-id=\"600\"]').click();true");await click('entity-locate')
            red=await until(lambda s:s['models'].get('600',{}).get('outline')=='#f8ffff' and s['models'].get('400',{}).get('outline')=='#071a2c' and s['tilesLoaded'])
            assert red['models']['600']['color']=='#ff4265' and '红方' in red['detail'];await shot('red-model-paused')
            result['affiliationDisplay']=dict(status='passed',blue=['400','500'],red=['600'],backendValuesUnchanged=True,redSelected=red)
            result['interactionChecks']=dict(status='passed',locate=True,follow=True,reset=True,layers=True,frozenTime=True)
            origin=paused['timeOrigin'];await cdp.call('Page.reload',{'ignoreCache':True},session)
            refreshed=await until(lambda s:s['timeOrigin']!=origin and s.get('map')=='true' and s.get('business',{}).get('phase')=='live' and s.get('entities',{}).get('count')==3)
            assert not refreshed['business']['sampleCounts'] and all(p['trailPoints']==0 for p in refreshed['entities']['objects'].values())
            result['refreshedPaused']=refreshed;result['refreshedPoseCheck']=pose_check(cdp.events,session,refreshed,grid)
            (directory/'verified').touch();deadline=time.monotonic()+45
            while not (directory/'gateway-stopped').exists():assert time.monotonic()<deadline;await asyncio.sleep(.1)
            offline=await until(lambda s:s.get('entities',{}).get('count')==0 and s.get('business',{}).get('phase')!='live',20)
            assert offline['entities']['followed'] is None and offline['entities']['selected'] is None;result['offline']=offline
            assert not [e for e in cdp.events if e['method'] in ('Runtime.exceptionThrown','Network.webSocketFrameSent')]
            result.update(status='passed',browser=version['Browser'])
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
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args();asyncio.run(verify(a.url,a.output))
