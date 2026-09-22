"""Actual Cesium rendering compared with received G4 frames; fixtures explicitly separated."""
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
import time
from urllib.request import urlopen
from websockets.asyncio.client import connect

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('mission_previous_browser',ROOT/'tests/g5_entities/browser.py');previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
spec=importlib.util.spec_from_file_location('mission_reference_browser',ROOT/'tests/g5_missions/reference.py');reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
spec=importlib.util.spec_from_file_location('coverage_native_check',ROOT/'tests/g5_coverage/checks.py');native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
save=previous.save;DevTools=previous.DevTools
EXPRESSION="""(()=>{
 const v=window.__g5Map?.viewer,rendered={};
 if(v)for(let i=0;i<v.dataSources.length;i++){const s=v.dataSources.get(i);if(s.name==='航线、任务与区域')for(const e of s.entities.values){const t=v.clock.currentTime,p=e.polyline?.positions?.getValue(t),a=e.polygon?.hierarchy?.getValue(t),w=e.wall?.positions?.getValue(t),q=e.position?.getValue(t);const points=p??a?.positions??w??(q?[q]:[]);rendered[e.id]={show:e.show,positions:points.map(x=>[x.x,x.y,x.z]),kind:p?'line':a?'area':w?'wall':'point'};}}
 const gl=v?.scene.context._gl,ext=gl?.getExtension('WEBGL_debug_renderer_info');
 return {coverage:window.__g5Coverage?.inspect(),coverageRendered:(()=>{const result={};if(v)for(let i=0;i<v.dataSources.length;i++){const s=v.dataSources.get(i);if(s.name==='当前传感器覆盖'||s.name==='累计侦察覆盖')result[s.name]={show:s.show,objects:s.entities.values.map(e=>({id:e.id,positions:(e.polygon?.hierarchy?.getValue(v.clock.currentTime)?.positions??e.polyline?.positions?.getValue(v.clock.currentTime)??(e.position?[e.position.getValue(v.clock.currentTime)]:[])).map(p=>[p.x,p.y,p.z]),rectangle:e.rectangle?(()=>{const r=e.rectangle.coordinates.getValue(v.clock.currentTime);return [r.west,r.south,r.east,r.north];})():null}))};}return result;})(),business:window.__g5State?.inspect(),entities:window.__g5Entities?.inspect(),missions:window.__g5Missions?.inspect(),rendered,timeOrigin:performance.timeOrigin,tilesLoaded:v?.scene.globe.tilesLoaded,renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):null,antiAliasing:{msaaSamples:v?.scene.msaaSamples,fxaa:v?.scene.postProcessStages.fxaa.enabled},detail:document.querySelector('#mission-details')?.textContent,error:document.querySelector('#backend-error')?.textContent,cameraHeight:v?.camera.positionCartographic.height};})()"""

def check(state,grid,events,session):
    assert state['antiAliasing']==dict(msaaSamples=1,fxaa=True)
    previous.previous.replay(events,session,state['business'])
    raw=state['business']['state'];features=state['missions']['features'];rendered=state['rendered'];error=0
    assert all(not f.get('error') for f in features.values()),[(k,f.get('error')) for k,f in features.items() if f.get('error')]
    for key,row in raw['routes'].items():
        feature=features['plan:'+key];wps=row['planned_mission']['WaypointList'];assert len(feature['waypoints'])==len(wps)
        assert [w['id'] for w in feature['waypoints']]==[w['Number'] for w in wps]
        lookup={w['Number']:w for w in wps};pairs=[(w,lookup[w['NextWaypoint']]) for w in wps if w['NextWaypoint']!=w['Number'] and w['NextWaypoint'] in lookup]
        assert len(feature['drawings'])==len(pairs)
        for drawing,pair in zip(feature['drawings'],pairs):
            for p,ecef in zip(pair,drawing['ecef']):
                expected=previous.ecef(dict(longitude_deg=p['Longitude'],latitude_deg=p['Latitude'],altitude_m=p['Altitude'],altitude_reference=p['AltitudeType']),grid)
                distance=math.dist(expected,ecef);error=max(error,distance);assert distance<=1
    for key,f in features.items():
        for i,d in enumerate(f['drawings']):
            actual=rendered['mission:'+key+':'+str(i)];assert len(actual['positions'])==len(d['ecef'])
            assert all(math.dist(p,q)<1e-6 for p,q in zip(actual['positions'],d['ecef']))
        if f['category']=='tasks':
            task=raw['tasks'][key.split(':')[1]];assert (f['status']=='后端报告完成')==(task.get('backend_completed') is True)
            definition=task['definition']
            if task['kind'] in ('point','line'):
                points=[definition['SearchLocation']] if task['kind']=='point' else definition['PointList']
                actual=f['drawings'][0]['ecef'];assert len(points)==len(actual)
                for p,q in zip(points,actual):
                    expected=previous.ecef(dict(longitude_deg=p['Longitude'],latitude_deg=p['Latitude'],altitude_m=p['Altitude'],altitude_reference=p['AltitudeType']),grid)
                    assert math.dist(expected,q)<=1
            elif task['kind']=='area':
                shape=definition['SearchArea'];center=shape['CenterPoint']
                corners=reference.corners((center['Longitude'],center['Latitude']),shape['Width'],shape['Height'],shape['Rotation'])
                actual=f['drawings'][0]['vertices'];assert all(min(math.hypot(v['longitude']-lon,v['latitude']-lat) for v in actual)<1e-9 for lon,lat in corners)
        if f['category']=='execution' and f.get('evidence'):
            e=f['evidence'];row=raw['entities'][f['entityIds'][0]];assert e['commandId']==row['current_command_id'] and e['currentWaypoint']==row['current_waypoint_id']
    return dict(status='passed',features=len(features),renderedObjects=len(rendered),maximumPlannedPositionErrorMeters=error)

def verify_advances(events,session,observations):
    requests=[e['params']['requestId'] for e in events if e.get('sessionId')==session and e['method']=='Network.webSocketCreated'];assert requests
    last={};transitions=set();edges=set()
    for event in events:
        if event.get('sessionId')!=session or event['method']!='Network.webSocketFrameReceived' or event['params']['requestId']!=requests[-1]:continue
        response=event['params']['response']
        if response['opcode']!=1:continue
        message=json.loads(response['payloadData'])
        if message['kind']!='delta':continue
        for change in message['changes']:
            if change['op']!='upsert':continue
            row=change['value']
            if change['collection']=='commands' and row.get('kind')=='mission':
                for w in row['message']['WaypointList']:edges.add((row['entity_id'],row['command_id'],w['Number'],w['NextWaypoint']))
            if change['collection']=='entities' and row.get('current_command_id'):
                entity=change['id'];old=last.get(entity)
                if old and old['current_command_id']==row['current_command_id'] and int(old['simulation_time_ms'])<int(row['simulation_time_ms']) and old['current_waypoint_id']!=row['current_waypoint_id']:
                    transitions.add((entity,row['current_command_id'],old['current_waypoint_id'],row['current_waypoint_id']))
                last[entity]=row
    seen={(e['entity'],e['commandId'],e['previousWaypoint'],e['currentWaypoint']) for row in observations for e in row}
    assert seen and seen.issubset(transitions) and seen.issubset(edges),(seen-transitions,seen-edges)
    return dict(status='passed',uniqueObservedSegments=len(seen),independentReceivedTransitions=len(transitions))

async def verify(url,directory,fixture_server=None):
    directory=directory.resolve();directory.mkdir(parents=True)
    context=json.loads((directory.parent.parent/'context.json').read_text(encoding='utf-8'));service=json.loads((Path(context['entityCandidate'])/'service.json').read_text(encoding='utf-8'))
    grid=json.loads((Path(service['dist'])/'entities/runtime.json').read_text(encoding='utf-8'))['height']
    edge=Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    with socket.socket() as probe:probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);probe.bind(('127.0.0.1',9223))
    arguments=[str(edge),'--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-background-mode','--disable-extensions','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost','--remote-debugging-address=127.0.0.1','--remote-debugging-port=9223','--window-size=1440,1100','--user-data-dir='+str(directory/'profile'),'about:blank']
    result=dict(status='running',scope='independent-regions-protocol-rendering' if fixture_server else 'real-backend-missions',offline=True);process=ws=cdp=None
    with (directory/'stdout.log').open('wb') as stdout,(directory/'stderr.log').open('wb') as stderr:
        try:
            process=subprocess.Popen(arguments,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+25;version=None
            while time.monotonic()<deadline:
                assert process.poll() is None
                try:
                    with urlopen('http://127.0.0.1:9223/json/version',timeout=.5) as response:version=json.load(response)
                    break
                except OSError:await asyncio.sleep(.1)
            assert version;ws=await connect(version['webSocketDebuggerUrl'],max_size=64*1024*1024);cdp=DevTools(ws)
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
                    await asyncio.sleep(.25)
                save(directory/'timeout-state.json',last);raise AssertionError('Mission browser timeout')
            async def shot(name):
                image=await cdp.call('Page.captureScreenshot',{'format':'png'},session);(directory/(name+'.png')).write_bytes(base64.b64decode(image['data']))
            async def click(identity):await evaluate('document.getElementById('+json.dumps(identity)+').click();true')
            async def choose(category,key):
                await evaluate('(()=>{const s=document.getElementById("mission-category");s.value='+json.dumps(category)+';s.dispatchEvent(new Event("change"));document.querySelector('+json.dumps('[data-feature="'+key+'"]')+').click();return true;})()')
            await cdp.call('Page.navigate',{'url':url},session)
            await until(lambda s:s.get('business') and s['business']['attempts']>0,45);(directory/'opened').touch()
            live=await until(lambda s:s.get('business',{}).get('phase')=='live' and s.get('missions') and any(k.startswith('plan:') for k in s['missions']['features']),150)
            live=await until(lambda s:s.get('coverage',{}).get('snapshot') and len(s['coverage']['sensors'])==3,40)
            result['initialCheck']=check(live,grid,cdp.events,session);result['initial']=live;result['renderer']=live['renderer']
            if fixture_server:
                assert len(live['business']['state']['zones'])==4
                await choose('zones','zone:21');await click('mission-locate');await until(lambda s:s['tilesLoaded']);await asyncio.sleep(1)
                await shot('independent-region-height-volume');assert 'AGL' in (await evaluate(EXPRESSION))['detail'] and 'MSL' in (await evaluate(EXPRESSION))['detail']
                await choose('zones','zone:region:24');assert '允许区' in (await evaluate(EXPRESSION))['detail']
                await choose('plans','plan:9223372036854775807')
                await evaluate('document.getElementById("waypoint-query").value="9223372036854775807";document.getElementById("waypoint-query-button").click();true')
                assert (await evaluate(EXPRESSION))['missions']['waypoint']=='9223372036854775807'
                await choose('zones','zone:21');(fixture_server/'delete-regions').touch()
                deleted=await until(lambda s:not s['business']['state']['zones'] and s['missions']['selected'] is None)
                assert not any(k.startswith('zone:') for k in deleted['missions']['features']);assert not any(k.startswith('mission:zone:') for k in deleted['rendered'])
                result['deletion']=check(deleted,grid,cdp.events,session);await shot('independent-regions-deleted')
                result.update(largeWaypointQuery=True,zoneTypes=['KeepInZone/Rectangle','KeepOutZone/Circle','KeepOutZone/Polygon','OperatingRegion'],syntheticOnly=True)
            else:
                initial_plans={k:json.dumps(v['planned_mission'],sort_keys=True) for k,v in live['business']['state']['routes'].items()}
                assert set(initial_plans)=={'400','500','600'};assert len(live['business']['state']['tasks']['3000']['definition']['PointList'])==90
                await choose('plans','plan:400');await click('mission-locate');await until(lambda s:s['tilesLoaded']);await shot('real-full-planned-route')
                await evaluate('document.getElementById("waypoint-query").value="1";document.getElementById("waypoint-query-button").click();true')
                assert (await evaluate(EXPRESSION))['missions']['waypoint']=='1'
                await choose('tasks','task:3002');await click('mission-locate');await until(lambda s:s['tilesLoaded']);await shot('real-area-task')
                await evaluate('document.querySelector('+json.dumps('[data-related-entity="600"]')+').click();true');assert (await evaluate(EXPRESSION))['entities']['selected']=='600'
                for category in ('plans','commands','execution','tasks','zones'):
                    await evaluate('document.querySelector('+json.dumps('[data-layer="'+category+'"]')+').click();true')
                    hidden=await evaluate(EXPRESSION);assert hidden['missions']['visible'][category] is False
                    assert all(not obj['show'] for key,obj in hidden['rendered'].items() if hidden['missions']['features'][key.removeprefix('mission:').rsplit(':',1)[0]]['category']==category)
                    await evaluate('document.querySelector('+json.dumps('[data-layer="'+category+'"]')+').click();true')
                await click('entity-reset');await choose('execution','execution:400')
                observations=[];deadline=time.monotonic()+180;terminal=None
                while time.monotonic()<deadline:
                    current=await evaluate(EXPRESSION);raw=current['business']['state'];features=current['missions']['features']
                    assert not current['error'];assert initial_plans=={k:json.dumps(v['planned_mission'],sort_keys=True) for k,v in raw['routes'].items()},'Segment replaced full plan'
                    observed=[f['evidence']|dict(entity=f['entityIds'][0]) for f in features.values() if f['category']=='execution' and f.get('evidence',{}).get('previousWaypoint')]
                    if observed and (not observations or observed!=observations[-1]):observations.append(observed)
                    if all(raw['tasks'][k].get('backend_completed') for k in ('3001','3002')) and observations:terminal=current;break
                    await asyncio.sleep(.5)
                assert terminal,'No real point/area completion and target advance evidence'
                assert all(k in terminal['missions']['features'] for k in ('task:3001','task:3002','plan:500','plan:600','execution:500','execution:600'))
                assert terminal['entities']['count']==3;result['completedCheck']=check(terminal,grid,cdp.events,session)
                result['advanceEvidence']=verify_advances(cdp.events,session,observations)
                await asyncio.sleep(1.5);continued=await evaluate(EXPRESSION)
                distances={entity:math.dist(terminal['entities']['objects'][entity]['position'],continued['entities']['objects'][entity]['position']) for entity in ('500','600')}
                assert all(d>1 for d in distances.values()),'Completed entity stopped displaying motion';result['postCompletionMovementMeters']=distances
                result['observedAdvances']=observations;result['completedTasks']=['3001','3002'];result['retainedLineVertices']=90
                # Both controls hide only their own layer; collection continues while hidden.
                await click('coverage-current');hidden=await evaluate(EXPRESSION)
                assert not hidden['coverage']['currentVisible'] and hidden['coverage']['accumulatedVisible']
                assert not hidden['coverageRendered']['当前传感器覆盖']['show'] and hidden['coverageRendered']['累计侦察覆盖']['show']
                await click('coverage-current');await click('coverage-accumulated');hidden=await evaluate(EXPRESSION)
                assert hidden['coverage']['currentVisible'] and not hidden['coverage']['accumulatedVisible']
                states=hidden['coverage']['snapshot']['sampledStates']
                await until(lambda s:s['coverage']['snapshot'] and s['coverage']['snapshot']['sampledStates']>states,15)
                await click('coverage-accumulated');result['independentTogglesAndBackgroundAccumulation']=True
                save(directory/'completed-state.json',terminal);await choose('tasks','task:3001');await shot('real-completed-point-retained')
                (directory/'request-pause').touch();paused=await until(lambda s:s['business']['state']['simulation'].get('state')==2)
                paused=await until(lambda s:s.get('coverage',{}).get('snapshot') and int(s['coverage']['snapshot']['simulationTimeMs'])==max(int(e['simulation_time_ms']) for e in s['business']['state']['entities'].values()),30)
                deadline=time.monotonic()+60
                while not (directory.parent/'amase/analysis-done').exists():assert time.monotonic()<deadline;await asyncio.sleep(.1)
                result['nativeCoverageComparison']=native.native(directory.parent/'amase',paused['coverage']['snapshot'])
                assert paused['coverage']['accumulatedObjects']>0 and len(paused['coverage']['sensors'])==3
                settings=json.loads((Path(service['dist'])/'missions/runtime.json').read_text());g=settings['ground']
                import array
                ground=array.array('f');ground.frombytes((Path(service['dist'])/'missions/orthometric.f32').read_bytes())
                errors=[]
                for key,sensor in paused['coverage']['sensors'].items():
                    entity,camera=key.split(':');row=paused['business']['state']['entities'][entity]
                    raw=next(p for p in row['state']['PayloadStateList'] if p['_type']=='afrl.cmasi.CameraState' and p['PayloadID']==camera)
                    assert sensor['raw']==[[p['Longitude'],p['Latitude']] for p in raw['Footprint']]
                    assert sensor['time']==row['simulation_time_ms']
                    rendered=next(e for e in paused['coverageRendered']['当前传感器覆盖']['objects'] if e['id']=='sensor:'+key)
                    for (lon,lat),actual in zip(sensor['points'],rendered['positions']):
                        h=reference.bilinear(lon,lat,g,ground)+reference.bilinear(lon,lat,grid,grid['values'])
                        errors.append(math.dist(reference.ecef(lon,lat,h),actual))
                assert errors and max(errors)<1
                result['footprintMaximumHeightConversionErrorMeters']=max(errors)
                def world(lon,lat):return reference.ecef(lon,lat,reference.bilinear(lon,lat,g,ground)+reference.bilinear(lon,lat,grid,grid['values']))
                result['renderedCumulativeCells']=native.rendered(paused['coverage']['snapshot'],paused['coverageRendered']['累计侦察覆盖']['objects'],world)
                layout=await evaluate('(()=>{const e=document.getElementById("entity-panel").getBoundingClientRect(),c=document.getElementById("coverage-panel").getBoundingClientRect(),m=document.getElementById("mission-panel").getBoundingClientRect();return {entityHeight:e.height,coverageTop:c.top,missionTop:m.top};})()')
                assert layout['entityHeight']>=160 and layout['coverageTop']<layout['missionTop'],'Sidebar compressed or coverage controls misplaced'
                result['sidebarLayout']=layout
                result['pausedCoverage']=paused['coverage']
                await choose('tasks','task:3002');await click('mission-locate');await until(lambda s:s['tilesLoaded']);await shot('current-and-accumulated-coverage')
                await click('coverage-current');await shot('accumulated-only');await click('coverage-accumulated');await shot('both-hidden');await click('coverage-current');await shot('current-only');await click('coverage-accumulated')
                result['pausedCheck']=check(paused,grid,cdp.events,session)
                origin=paused['timeOrigin'];await cdp.call('Page.reload',{'ignoreCache':True},session)
                refreshed=await until(lambda s:s['timeOrigin']!=origin and s.get('business',{}).get('phase')=='live' and len(s.get('missions',{}).get('features',{}))==len(paused['missions']['features']))
                assert all(not f.get('evidence',{}).get('previousWaypoint') for f in refreshed['missions']['features'].values() if f['category']=='execution')
                refreshed=await until(lambda s:s.get('coverage',{}).get('snapshot') and s['coverage']['snapshot']['tasks']==paused['coverage']['snapshot']['tasks'],35)
                result['coverageRestoredAfterRefresh']=True
                result['refreshedCheck']=check(refreshed,grid,cdp.events,session);(directory/'verified').touch()
                deadline=time.monotonic()+45
                while not (directory/'gateway-stopped').exists():assert time.monotonic()<deadline;await asyncio.sleep(.1)
                offline=await until(lambda s:not s.get('missions',{}).get('features') and s['missions']['renderedObjects']==0 and s['business']['phase']!='live',20)
                assert offline['coverage']['currentObjects']==0 and offline['coverage']['accumulatedObjects']==0 and offline['coverage']['snapshot'] is None
                result['offlineCleared']=True
            assert not [e for e in cdp.events if e['method'] in ('Runtime.exceptionThrown','Network.webSocketFrameSent')]
            result.update(status='passed',browser=version['Browser'])
        except BaseException as error:
            result.update(status='failed',error=str(error))
            if cdp:
                try:await shot('failure')
                except Exception:pass
            raise
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
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--fixture-server',type=Path);a=parser.parse_args();asyncio.run(verify(a.url,a.output,a.fixture_server))
