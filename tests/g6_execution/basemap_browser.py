"""Check the B04 startup basemap in real Edge, with or without external DNS."""
import argparse
import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from websockets.asyncio.client import connect

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('g5_map_browser',ROOT/'tests/g5_map/map_browser.py')
map_browser=importlib.util.module_from_spec(spec);spec.loader.exec_module(map_browser)

STATE="""(()=>({ready:document.documentElement.dataset.ready,
  base:document.querySelector('#base-layer')?.value,
  notice:document.querySelector('#notice')?.textContent,
  layers:window.__g5Map?.viewer.imageryLayers.length,
  tilesLoaded:window.__g5Map?.viewer.scene.globe.tilesLoaded,
  localTiles:window.__g5Map?.vector.metrics.tiles,
  errors:window.__g5Map?.errors}))()"""

async def verify(output,online):
    output.mkdir(parents=True,exist_ok=False)
    edge=Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        probe.bind(('127.0.0.1',9225))
    args=[str(edge),'--headless=new','--no-first-run','--no-default-browser-check',
          '--disable-background-networking','--disable-background-mode','--disable-extensions',
          '--remote-debugging-address=127.0.0.1','--remote-debugging-port=9225',
          '--window-size=1440,1000','--user-data-dir='+str(output/'profile'),'about:blank']
    if not online:
        args.append('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost')
    result=dict(task='G6-B04-basemap',mode='online' if online else 'offline',status='running')
    process=ws=cdp=None
    with (output/'stdout.log').open('wb') as stdout,(output/'stderr.log').open('wb') as stderr:
        try:
            process=subprocess.Popen(args,stdout=stdout,stderr=stderr,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+25;version=None
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Edge exited before CDP startup')
                try:
                    with urlopen('http://127.0.0.1:9225/json/version',timeout=.5) as response:
                        version=json.load(response)
                    break
                except OSError:await asyncio.sleep(.1)
            if not version:raise TimeoutError('Edge CDP unavailable')
            ws=await connect(version['webSocketDebuggerUrl'],max_size=32*1024*1024)
            cdp=map_browser.DevTools(ws)
            target=await cdp.call('Target.createTarget',{'url':'about:blank'})
            session=(await cdp.call('Target.attachToTarget',
                     {'targetId':target['targetId'],'flatten':True}))['sessionId']
            for method in ('Page.enable','Runtime.enable','Network.enable'):
                await cdp.call(method,session=session)
            await cdp.call('Page.navigate',{'url':'http://127.0.0.1:8080/'},session=session)
            deadline=time.monotonic()+35;state=None;tiles=[]
            while time.monotonic()<deadline:
                reply=await cdp.call('Runtime.evaluate',
                    {'expression':STATE,'returnByValue':True},session=session)
                state=reply.get('result',{}).get('value') or {}
                tiles=[e['params']['response']['url'] for e in cdp.events
                       if e['method']=='Network.responseReceived'
                       and e['params']['response']['status']==200
                       and '/World_Imagery/MapServer/tile/' in e['params']['response']['url']]
                if online and state.get('base')=='satellite' and state.get('layers')==2 and tiles:
                    break
                if not online and state.get('base')=='local' and state.get('layers')==1 \
                        and state.get('ready')=='true' and '恢复本地矢量底图' in (state.get('notice') or ''):
                    break
                await asyncio.sleep(.2)
            else:raise TimeoutError('Basemap did not reach expected state: '+str(state))
            await asyncio.sleep(4)
            reply=await cdp.call('Runtime.evaluate',
                {'expression':STATE,'returnByValue':True},session=session)
            state=reply.get('result',{}).get('value') or {}
            if online and not (state.get('base')=='satellite' and state.get('layers')==2
                               and state.get('tilesLoaded')):
                raise RuntimeError('Esri imagery did not remain visible: '+str(state))
            if not online and not (state.get('base')=='local' and state.get('layers')==1
                                   and state.get('ready')=='true'):
                raise RuntimeError('Local basemap did not remain available: '+str(state))
            shot=await cdp.call('Page.captureScreenshot',{'format':'png'},session=session)
            (output/'basemap.png').write_bytes(base64.b64decode(shot['data']))
            result.update(status='passed',state=state,esriTileResponses=len(tiles),browser=version['Browser'])
        except Exception as error:
            result.update(status='failed',error=str(error),state=state if 'state' in locals() else None)
        finally:
            if cdp is not None:
                try:await cdp.call('Browser.close')
                except Exception:pass
            if ws is not None:await ws.close()
            if process is not None:
                try:process.wait(timeout=12)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                result['edgeExitCode']=process.returncode
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if result['status']=='passed' else 1

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--online',action='store_true')
    args=parser.parse_args()
    return asyncio.run(verify(args.output.resolve(),args.online))

if __name__=='__main__':sys.exit(main())
