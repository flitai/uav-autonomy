"""Real ordinary-session startup and early normal stop, not mission qualification."""
import argparse
import asyncio
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
from websockets.asyncio.client import connect


async def websocket(run_id,count):
    async with connect('ws://127.0.0.1:8000/api/v1/stream',max_size=8388608) as socket:
        snapshot=json.loads(await asyncio.wait_for(socket.recv(),5))
        assert snapshot['kind']=='snapshot' and snapshot['run_id']==run_id and len(snapshot['state']['entities'])==count
        delta=json.loads(await asyncio.wait_for(socket.recv(),5))
        assert delta['kind']=='delta' and int(delta['sequence'])==int(snapshot['sequence'])+1
        return {'run_id':run_id,'entities':count,'stream_id':snapshot['stream_id'],'snapshotSequence':snapshot['sequence'],'deltaSequence':delta['sequence']}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--baseline-run-id',required=True)
    args=parser.parse_args(); root=args.root.resolve()
    spec=importlib.util.spec_from_file_location('smoke_package',root/'scripts/g4_stage/package.py')
    package=importlib.util.module_from_spec(spec); spec.loader.exec_module(package)
    sources=package.files(root,[Path(__file__),*sorted((root/'scripts/g4_stage').glob('*.py'))])
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f'); output=root/'out/runs'/('g4-t09-session-smoke-'+stamp); output.mkdir()
    bundle=package.build(root,args.baseline_run_id); cases=[]
    java=root/'.tools/jdk-11.0.32.1+1'
    for scene,count in [('Original',2),('Mixed20',20)]:
        identity='g4-t09-demo-'+scene.lower()+'-'+stamp; directory=root/'out/runs'/identity
        with (output/(scene+'.stdout')).open('wb') as stdout,(output/(scene+'.stderr')).open('wb') as stderr:
            process=subprocess.Popen([sys.executable,'-I','-B','-X','utf8',str(root/'scripts/g4_stage/session.py'),
                '--root',str(root),'--java-home',str(java),'--bundle',str(bundle),'--baseline-run-id',args.baseline_run_id,
                '--run-id',identity,'--scene',scene,'--mode','Headless'],cwd=output,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+120; ready=False
            while time.monotonic()<deadline:
                assert process.poll() is None,'Session exited before ready: '+identity
                path=directory/'result.json'
                if path.exists() and package.load(path)['status']=='demonstration-running': ready=True; break
                time.sleep(.2)
            assert ready,'Session readiness timed out'
            with urlopen('http://127.0.0.1:8000/api/v1/health') as response: health=json.load(response)
            assert health['ready'] and health['error'] is None
            proof=asyncio.run(websocket(health['run_id'],count))
        finally:
            if directory.exists(): (directory/'request-stop').touch()
            process.wait(timeout=45)
        receipt=package.load(directory/'result.json')
        assert process.returncode==0 and receipt['status']=='passed' and receipt['demonstrationOnly'] and not receipt['stageQualified'],receipt
        assert len(receipt['cases'])==1 and receipt['cases'][0]['normalExit'] and receipt['cases'][0]['portsReleased']
        assert len(receipt['cases'][0]['gatewayInstances'])==1,'Ordinary session injected a restart'
        cases.append(dict(scene=scene,runId=identity,resultSHA256=package.sha(directory/'result.json'),websocket=proof))
    package.verify_files(root,sources)
    package.save(output/'result.json',dict(status='passed',cases=cases,candidate=str(bundle.relative_to(root)),sources=sources))
    print(output.name+' passed'); return 0


if __name__=='__main__': sys.exit(main())
