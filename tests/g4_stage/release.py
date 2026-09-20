"""Consume the published Windows session entry from another working directory."""
import argparse
import asyncio
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import urlopen
from websockets.asyncio.client import connect


async def observe(run_id,count):
    async with connect('ws://127.0.0.1:8000/api/v1/stream',max_size=8388608) as socket:
        snapshot=json.loads(await asyncio.wait_for(socket.recv(),5))
        assert snapshot['kind']=='snapshot' and snapshot['run_id']==run_id and len(snapshot['state']['entities'])==count
        delta=json.loads(await asyncio.wait_for(socket.recv(),5))
        assert delta['kind']=='delta' and delta['stream_id']==snapshot['stream_id'] and int(delta['sequence'])==int(snapshot['sequence'])+1
        return dict(runId=run_id,entities=count,sequence=snapshot['sequence'],nextSequence=delta['sequence'])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--python',type=Path,required=True)
    args=parser.parse_args(); root=args.root.resolve()
    spec=importlib.util.spec_from_file_location('release_entry',root/'scripts/g4_stage/entry.py')
    entry=importlib.util.module_from_spec(spec); spec.loader.exec_module(entry); package=entry.package
    bundle,pointer,_=entry.resolve(root)
    identity='g4-t09-release-check-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output=root/'out/runs'/identity; output.mkdir(); cwd=output/'中文 空格 working'; cwd.mkdir()
    sources=package.files(root,[Path(__file__),*sorted((root/'scripts/g4_stage').glob('*.py')),*sorted((root/'scripts/g4_finalize').glob('*.py')),
        root/'scripts/g4_session/runtime.py',root/'scripts/windows/start-g4-session.ps1'])
    cases=[]
    for scene,count in [('Original',2),('Mixed20',20)]:
        stdout_path=output/(scene+'.stdout'); stderr_path=output/(scene+'.stderr'); directory=None
        with stdout_path.open('wb') as stdout,stderr_path.open('wb') as stderr:
            process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                str(root/'scripts/windows/start-g4-session.ps1'),'-PythonExecutable',str(args.python.resolve()),'-Scene',scene,'-Mode','Headless','-ValidateEntry'],
                cwd=cwd,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+240; ready=False
            while time.monotonic()<deadline:
                assert process.poll() is None,'Published entry exited early: '+scene
                ids=re.findall(r'^G4_SESSION_RUN_ID=(g4-t09-demo-[0-9-]+)',stdout_path.read_text(encoding='utf-8-sig'),re.MULTILINE)
                if ids:
                    assert len(ids)==1; directory=root/'out/runs'/ids[0]; path=directory/'result.json'
                    if path.exists() and package.load(path)['status']=='demonstration-running': ready=True; break
                time.sleep(.2)
            assert ready,'Published entry readiness timed out'
            with urlopen('http://127.0.0.1:8000/api/v1/health',timeout=5) as response: health=json.load(response)
            assert health['ready'] and health['error'] is None
            proof=asyncio.run(observe(health['run_id'],count))
            host=directory/'session-headless/gateway-host'
            manifest_before=(host/'manifest.json').read_bytes()
            (directory/'gateway-offline').touch()
            (host/'instance-1/observer/request-stop').touch()
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                status_path=directory/'observer-status.json'
                if status_path.exists() and package.load(status_path)['status']=='offline': break
                assert process.poll() is None; time.sleep(.2)
            else: raise AssertionError('Observer did not stop independently')
            time.sleep(3)
            assert process.poll() is None and not (directory/'request-stop').exists()
            (directory/'gateway-offline').unlink()
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                assert process.poll() is None,'Backend stopped with observer'
                try:
                    with urlopen('http://127.0.0.1:8000/api/v1/health',timeout=2) as response: recovered=json.load(response)
                    if recovered['ready'] and recovered['stream_id']!=health['stream_id']: break
                except OSError: pass
                time.sleep(.2)
            else: raise AssertionError('Observer did not recover')
            assert recovered['run_id']==health['run_id'] and int(recovered['source_time_ms'])>int(health['source_time_ms'])
            assert (host/'manifest.json').read_bytes()==manifest_before
            recovery_proof=asyncio.run(observe(recovered['run_id'],count))
        finally:
            if directory and directory.is_dir(): (directory/'request-stop').touch()
            process.wait(timeout=60)
        result=package.load(directory/'result.json')
        assert process.returncode==0 and result['status']=='passed' and result['demonstrationOnly'] and not result['stageQualified']
        case=result['cases'][0]; assert case['normalExit'] and case['portsReleased'] and len(case['gatewayInstances'])==2
        assert case['observerLifetimeIndependent'] and len(case['observerExits'])==1
        assert case['observerExits'][0]['exitCode']==0 and not case['observerExits'][0]['backendStopRequested']
        launch=package.load(directory/case['name']/'gateway-host/instance-1/package-launch.json')
        assert Path(launch['bundle'])==bundle and launch['packageSHA256']==pointer['packageSHA256']
        assert all(Path(item['path']).is_relative_to(bundle/'src') for item in launch['loaded'])
        cases.append(dict(scene=scene,runId=directory.name,resultSHA256=package.sha(directory/'result.json'),
            loadedFormalBundle=True,actualSnapshotAndDelta=proof,recoverySnapshotAndDelta=recovery_proof,
            gatewayRestartPreservedBackend=True,simulationAdvancedWhileObserverRestarted=True,
            normalExit=True,portsReleased=True,partialFlightOnly=True))
        print('Published '+scene+' entry passed',flush=True)
    assert package.load(root/'out/artifacts/gis-gateway/current.json')==pointer
    package.verify_files(root,sources)
    package.save(output/'result.json',dict(status='passed',runId=identity,pointer=pointer,cases=cases,sources=sources))
    package.save(root/'out/artifacts/gis-gateway/session.json',dict(path=(output/'result.json').relative_to(root).as_posix(),
        sha256=package.sha(output/'result.json')))
    print(identity+' passed'); return 0


if __name__=='__main__': sys.exit(main())
