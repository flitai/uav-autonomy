"""Compare a paused real twenty-entity page with the exact HTTP snapshot."""
import argparse
import asyncio
import base64
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


async def verify(root,run_id):
    spec=importlib.util.spec_from_file_location('stage_page_helpers',root/'tests/g4_web/browser.py')
    helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    spec=importlib.util.spec_from_file_location('stage_page_package',root/'scripts/g4_stage/package.py')
    package=importlib.util.module_from_spec(spec); spec.loader.exec_module(package)
    directory=root/'out/runs'/('g4-t09-browser-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')); directory.mkdir()
    with urlopen('http://127.0.0.1:8000/api/v1/snapshot',timeout=5) as response: snapshot=json.load(response)
    assert snapshot['run_id'].startswith(run_id+'/')
    assert len(snapshot['state']['entities'])==len(snapshot['state']['tasks'])==20
    assert all(t['backend_completed'] for t in snapshot['state']['tasks'].values())
    expected={key:sorted(value.keys()) for key,value in snapshot['state'].items() if key in ('entities','tasks')}
    expected_tasks={key:[key,{'point':'点搜索','line':'线搜索','area':'区域搜索'}[value['kind']],
                         '后端报告完成',', '.join(value['completed_entity_ids']),value['completed_time_ms']]
                    for key,value in snapshot['state']['tasks'].items()}
    edge=Path(os.environ['ProgramFiles(x86)'])/'Microsoft/Edge/Application/msedge.exe'
    with socket.socket() as probe: probe.bind(('127.0.0.1',9222))
    arguments=[str(edge),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
        '--disable-background-networking','--disable-background-mode','--disable-extensions','--remote-debugging-address=127.0.0.1',
        '--remote-debugging-port=9222','--window-size=1280,1800','--user-data-dir='+str(directory/'profile'),'about:blank']
    result={'status':'running','sourceSHA256':package.sha(Path(__file__)),'runId':run_id}
    with (directory/'stdout.log').open('wb') as stdout,(directory/'stderr.log').open('wb') as stderr:
        process=subprocess.Popen(arguments,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
    websocket=None; devtools=None
    try:
        version=None; deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            assert process.poll() is None
            try:
                with urlopen('http://127.0.0.1:9222/json/version',timeout=.5) as response: version=json.load(response)
                break
            except URLError: await asyncio.sleep(.1)
        assert version
        websocket=await connect(version['webSocketDebuggerUrl'],max_size=8388608); devtools=helper.DevTools(websocket)
        target=await devtools.call('Target.createTarget',{'url':'about:blank'})
        session=(await devtools.call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True}))['sessionId']
        await devtools.call('Runtime.enable',session=session); await devtools.call('Page.enable',session=session)
        await devtools.call('Page.navigate',{'url':'http://127.0.0.1:8000/'},session)
        expression="""(()=>({connection:document.getElementById('connection')?.textContent,
          entities:[...document.querySelectorAll('#entities tr')].map(r=>r.cells[0].textContent).sort(),
          tasks:[...document.querySelectorAll('#tasks tr')].map(r=>[...r.cells].map(c=>c.textContent)),
          sequence:typeof sequence==='bigint'?String(sequence):null,timeOrigin:performance.timeOrigin}))()"""
        async def rendered(previous=None):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                reply=await devtools.call('Runtime.evaluate',{'expression':expression,'returnByValue':True},session)
                value=reply.get('result',{}).get('value',{})
                if value.get('entities')==expected['entities'] and sorted(row[0] for row in value.get('tasks',[]))==expected['tasks'] and '已同步' in value.get('connection','') and value.get('timeOrigin')!=previous:
                    assert value['sequence']==snapshot['sequence']
                    assert {row[0]:row for row in value['tasks']}==expected_tasks,value['tasks']
                    return value
                await asyncio.sleep(.1)
            raise AssertionError('Current twenty-entity page did not match the paused snapshot')
        initial=await rendered(); await devtools.call('Page.reload',{'ignoreCache':True},session)
        refreshed=await rendered(initial['timeOrigin'])
        shot=await devtools.call('Page.captureScreenshot',{'format':'png'},session)
        (directory/'diagnostic.png').write_bytes(base64.b64decode(shot['data']))
        assert not devtools.errors
        result.update(status='passed',initial=initial,refreshed=refreshed,javascriptErrors=devtools.errors,entities=20,tasks=20)
    except Exception as error: result.update(status='failed',error=str(error)); raise
    finally:
        if devtools:
            try: await devtools.call('Browser.close')
            except ConnectionClosed: pass
        if websocket: await websocket.close()
        try: process.wait(timeout=30); result.update(exitCode=process.returncode,forcedTermination=False)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(); result.update(status='failed',forcedTermination=True)
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1',9222)); result['debugPortReleased']=True
            except OSError: result.update(status='failed',debugPortReleased=False)
        if process.returncode!=0: result['status']='failed'
        package.save(directory/'result.json',result)
    assert result['status']=='passed'; print(directory.name+' passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--run-id',required=True)
    args=parser.parse_args(); asyncio.run(verify(args.root.resolve(),args.run_id))
