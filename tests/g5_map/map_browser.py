"""Independent Edge/CDP acceptance against real PMTiles and qualified terrain."""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/g5_environment'))
from browser import DevTools

STATE="""(()=>{const m=window.__g5Map?.viewer.isDestroyed()?undefined:window.__g5Map,c=document.querySelector('#scene canvas'),g=c?.getContext('webgl2'),e=g?.getExtension('WEBGL_debug_renderer_info');return {
ready:document.documentElement.dataset.ready,notice:document.querySelector('#notice')?.textContent,
status:document.querySelector('#status')?.textContent,base:document.querySelector('#base-layer')?.value,
timeOrigin:performance.timeOrigin,renderer:e?g.getParameter(e.UNMASKED_RENDERER_WEBGL):null,
font:document.fonts.check('14px "Map CJK"'),metrics:m?.vector.metrics,labels:m?.vector.labels,
terrain:m?{requests:m.terrain.requests,errors:m.terrain.errors,peakActive:m.terrain.peakActive}:null,
errors:m?.errors,layers:m?.viewer.imageryLayers.length,tilesLoaded:m?.viewer.scene.globe.tilesLoaded,
heap:performance.memory?.usedJSHeapSize,resources:performance.getEntriesByType('resource').map(x=>x.name)}})()"""


async def verify(url,directory,online=False,quick=False,expect_failure=False):
    directory=directory.resolve()
    directory.mkdir(parents=True,exist_ok=False)
    edge=Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    assert edge.is_file()
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);probe.bind(('127.0.0.1',9223))
    args=[str(edge),'--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking',
        '--disable-background-mode','--disable-extensions','--remote-debugging-address=127.0.0.1','--remote-debugging-port=9223',
        '--window-size=1440,1000','--user-data-dir='+str(directory/'profile'),'about:blank']
    if not online:args.append('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost')
    result=dict(status='running',externalDNSDisabled=not online,realGeographicInputs=True,simulationConnected=False)
    process=None;ws=cdp=session=None
    with (directory/'stdout.log').open('wb') as stdout,(directory/'stderr.log').open('wb') as stderr:
        try:
            process=subprocess.Popen(args,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+25;version=None
            while time.monotonic()<deadline:
                assert process.poll() is None,'Edge exited before ready'
                try:
                    with urlopen('http://127.0.0.1:9223/json/version',timeout=.5) as response:version=json.load(response)
                    break
                except OSError:await asyncio.sleep(.1)
            assert version,'Edge endpoint timed out'
            ws=await connect(version['webSocketDebuggerUrl'],max_size=32*1024*1024);cdp=DevTools(ws)
            target=await cdp.call('Target.createTarget',{'url':'about:blank'})
            session=(await cdp.call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True}))['sessionId']
            for method in ('Runtime.enable','Page.enable','Network.enable'):await cdp.call(method,session=session)

            async def evaluate(expression):
                reply=await cdp.call('Runtime.evaluate',dict(expression=expression,returnByValue=True,awaitPromise=True),session)
                assert not reply.get('exceptionDetails'),reply
                return reply.get('result',{}).get('value')

            async def until(predicate,seconds=90):
                deadline=time.monotonic()+seconds;last=None
                while time.monotonic()<deadline:
                    last=await evaluate(STATE)
                    if last.get('ready')=='failed':raise AssertionError(last)
                    if predicate(last):return last
                    await asyncio.sleep(.2)
                raise AssertionError('Map state timeout: '+json.dumps(last,ensure_ascii=False))

            async def shot(name):
                image=await cdp.call('Page.captureScreenshot',{'format':'png'},session)
                (directory/(name+'.png')).write_bytes(base64.b64decode(image['data']))

            await cdp.call('Page.navigate',{'url':url},session)
            if expect_failure:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    state=await evaluate(STATE)
                    if state.get('ready')=='failed':
                        assert state.get('notice'),'Failure was not explained'
                        await shot('expected-resource-failure')
                        result.update(status='passed',expectedResourceFailure=state)
                        return
                    await asyncio.sleep(.2)
                raise AssertionError('Missing resource was not rejected')
            initial=await until(lambda s:s.get('ready')=='true' and s['metrics'].get('tiles',0)>=10)
            await shot('region');result['initial']=initial
            assert initial['renderer'] and initial['font'] and not initial['errors'],initial
            initial_responses=[e['params']['response'] for e in cdp.events if e['method']=='Network.responseReceived']
            assert not [r for r in initial_responses if r['url'].startswith(('https:','http:')) and not r['url'].startswith(url)],'Unrequested online resources'
            assert any('/cesium/Workers/' in x for x in initial['resources']+[r['url'] for r in initial_responses]),'Cesium terrain workers missing'
            if not quick:
                await evaluate("document.querySelector('#terrain-detail').click();true")
                await until(lambda s:s['tilesLoaded'])
                await shot('terrain-detail')
                await evaluate("document.querySelector('#terrain-toggle').click(); document.querySelector('#boundary-toggle').click(); true")
                assert await evaluate("window.__g5Map.viewer.entities.getById('terrain-qualification-boundary').show"), 'Boundary toggle failed'
                await evaluate("document.querySelector('#terrain-toggle').click(); document.querySelector('#boundary-toggle').click(); document.querySelector('#beijing-view').click(); true")
                beijing=await until(lambda s:s['metrics'].get('chineseLabels',0)>initial['metrics'].get('chineseLabels',0) and s['metrics']['tiles']>initial['metrics']['tiles']+15)
                await shot('beijing');result['beijing']=beijing
                await evaluate("document.querySelector('#global-view').click(); true")
                await asyncio.sleep(2)
                await evaluate("document.querySelector('#reset-view').click(); true")
                await until(lambda s:s['tilesLoaded'])
                await cdp.call('Page.reload',{'ignoreCache':True},session)
                result['refreshed']=await until(lambda s:s.get('ready')=='true' and s['timeOrigin']!=initial['timeOrigin'] and s['metrics'].get('tiles',0)>=10)
                await evaluate("document.querySelector('#base-layer').value='satellite';document.querySelector('#base-layer').dispatchEvent(new Event('change'));true")
                if online:
                    satellite=await until(lambda s:s['layers']==2,30)
                    await asyncio.sleep(4);await shot('satellite');result['satellite']=satellite
                    responses=[e['params']['response'] for e in cdp.events if e['method']=='Network.responseReceived']
                    assert any('/World_Imagery/MapServer/tile/' in r['url'] and r['status']==200 for r in responses),'No real Esri imagery response'
                    # Existing imagery is followed by a genuine failed request after cache invalidation.
                    await evaluate("document.querySelector('#base-layer').value='local';document.querySelector('#base-layer').dispatchEvent(new Event('change'));true")
                    await cdp.call('Network.setBlockedURLs',{'urls':['*services.arcgisonline.com*']},session)
                    await cdp.call('Network.setCacheDisabled',{'cacheDisabled':True},session)
                    await evaluate("document.querySelector('#base-layer').value='satellite';document.querySelector('#base-layer').dispatchEvent(new Event('change'));true")
                fallback=await until(lambda s:s['base']=='local' and '恢复本地' in (s.get('notice') or ''),25)
                result['fallback']=fallback;assert fallback['layers']==1
                await shot('fallback')
            final=await evaluate(STATE)
            assert final['metrics']['rangeCachePeak']<=16*1024*1024 and final['metrics']['directoryCachePeak']<=16*1024*1024
            assert final['metrics']['peakActive']<=4 and final['terrain']['peakActive']<=8 and final['metrics']['maximumRead']<=4*1024*1024
            exceptions=[e for e in cdp.events if e['method']=='Runtime.exceptionThrown'];assert not exceptions,exceptions
            result.update(status='passed',browser=version['Browser'],final=final,javascriptErrors=exceptions)
        except BaseException as error:
            result.update(status='failed',error=str(error));raise
        finally:
            if cdp:
                try:
                    if session:
                        snapshot=await cdp.call('Page.captureScreenshot',{'format':'png'},session)
                        (directory/'final.png').write_bytes(base64.b64decode(snapshot['data']))
                except Exception:pass
                try:await cdp.call('Browser.close')
                except Exception:pass
            if ws:await ws.close()
            if process:
                try:process.wait(timeout=30);result.update(exitCode=process.returncode,forcedTermination=False)
                except subprocess.TimeoutExpired:process.kill();process.wait();result.update(status='failed',forcedTermination=True)
                if process.returncode!=0:result['status']='failed'
            if cdp:
                result['networkResponses']=[e['params']['response'] for e in cdp.events if e['method']=='Network.responseReceived']
                result['networkFailures']=[e['params'] for e in cdp.events if e['method']=='Network.loadingFailed']
            (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert result['status']=='passed',result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--online',action='store_true');parser.add_argument('--quick',action='store_true');parser.add_argument('--expect-failure',action='store_true');args=parser.parse_args()
    asyncio.run(verify(args.url,args.output,args.online,args.quick,args.expect_failure))
