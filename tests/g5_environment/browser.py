"""Native Edge resource/render/refresh smoke, isolated profile and normal close."""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import urlopen
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


class DevTools:
    def __init__(self, websocket):
        self.ws, self.sequence, self.events = websocket, 0, []

    async def call(self, method, params=None, session=None):
        self.sequence += 1
        request = dict(id=self.sequence, method=method, params=params or {})
        if session: request['sessionId'] = session
        await self.ws.send(json.dumps(request))
        while True:
            response = json.loads(await asyncio.wait_for(self.ws.recv(), 30))
            if 'method' in response: self.events.append(response)
            if response.get('id') == self.sequence:
                assert 'error' not in response, response
                return response.get('result', {})


async def verify(url, directory):
    directory = directory.resolve()
    directory.mkdir(parents=True)
    edge = Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    assert edge.is_file(), 'Native Edge is required'
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1); probe.bind(('127.0.0.1', 9223))
    args = [str(edge), '--headless=new', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-background-mode', '--disable-extensions',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9223',
            '--window-size=1280,900', '--user-data-dir='+str(directory/'profile'), 'about:blank']
    result = dict(status='running', externalDNSDisabled=True, syntheticOnly=True)
    with (directory/'stdout.log').open('wb') as stdout, (directory/'stderr.log').open('wb') as stderr:
        process = subprocess.Popen(args, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        ws, cdp = None, None
        try:
            deadline = time.monotonic()+25; version=None
            while time.monotonic() < deadline:
                assert process.poll() is None, 'Edge exited before ready'
                try:
                    with urlopen('http://127.0.0.1:9223/json/version',timeout=.5) as response: version=json.load(response)
                    break
                except OSError: await asyncio.sleep(.1)
            assert version, 'Edge debugging endpoint timed out'
            ws=await connect(version['webSocketDebuggerUrl'],max_size=32*1024*1024); cdp=DevTools(ws)
            target=await cdp.call('Target.createTarget',{'url':'about:blank'})
            session=(await cdp.call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True}))['sessionId']
            for name in ('Runtime.enable','Page.enable','Network.enable'): await cdp.call(name, session=session)
            await cdp.call('Page.navigate',{'url':url},session)
            expression='''(()=>{const canvas=document.querySelector('canvas');const gl=canvas?.getContext('webgl2');
                const ext=gl?.getExtension('WEBGL_debug_renderer_info');return {
                ready:document.documentElement.dataset.ready,status:document.querySelector('#status')?.textContent,
                title:document.title,timeOrigin:performance.timeOrigin,canvasSize:canvas?[canvas.width,canvas.height]:null,
                renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):null,
                vendor:ext?gl.getParameter(ext.UNMASKED_VENDOR_WEBGL):null,
                font:document.fonts.check('16px "Microsoft YaHei"'),
                resources:performance.getEntriesByType('resource').map(x=>x.name)}})()'''
            async def rendered(old=None):
                deadline=time.monotonic()+60
                last={}
                while time.monotonic()<deadline:
                    reply=await cdp.call('Runtime.evaluate',{'expression':expression,'returnByValue':True},session)
                    last=reply.get('result',{}).get('value',{})
                    if last.get('ready')=='true' and last.get('timeOrigin')!=old: return last
                    if last.get('ready')=='failed': raise AssertionError(last)
                    await asyncio.sleep(.15)
                raise AssertionError('Cesium rendering timeout: '+json.dumps(last,ensure_ascii=False))
            initial=await rendered()
            await cdp.call('Page.reload',{'ignoreCache':True},session)
            refreshed=await rendered(initial['timeOrigin'])
            shot=await cdp.call('Page.captureScreenshot',{'format':'png'},session)
            (directory/'cesium.png').write_bytes(base64.b64decode(shot['data']))
            errors=[e for e in cdp.events if e['method']=='Runtime.exceptionThrown']
            responses=[e['params']['response'] for e in cdp.events if e['method']=='Network.responseReceived']
            urls=[r['url'] for r in responses]
            assert not errors, errors
            assert all(r['status']<400 for r in responses if r['url'].startswith(url)), responses
            assert any('/cesium/Workers/' in x for x in refreshed['resources']+urls), 'Geometry worker not loaded'
            assert refreshed['renderer'] and refreshed['font'] and '已就绪' in refreshed['status'], refreshed
            external=[u for u in urls if u.startswith(('http:','https:')) and not u.startswith(url)]
            assert not external, external
            result.update(status='passed',browser=version['Browser'],initial=initial,refreshed=refreshed,
                          javascriptErrors=errors,networkResponses=responses,renderer=refreshed['renderer'])
        except BaseException as error:
            result.update(status='failed',error=str(error)); raise
        finally:
            if cdp:
                try: await cdp.call('Browser.close')
                except ConnectionClosed: pass
            if ws: await ws.close()
            try: process.wait(timeout=30); result.update(exitCode=process.returncode,forcedTermination=False)
            except subprocess.TimeoutExpired:
                process.kill();process.wait();result.update(status='failed',exitCode=process.returncode,forcedTermination=True)
            if process.returncode!=0: result['status']='failed'
            (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert result['status']=='passed', result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();asyncio.run(verify(args.url,args.output))
