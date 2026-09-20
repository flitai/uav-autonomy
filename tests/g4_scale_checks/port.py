"""A duplicate gateway must refuse its occupied port without affecting the owner."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen

parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);args=parser.parse_args()
root=Path(__file__).resolve().parents[2];parent=root/'out/runs'/args.run_id
assert parent.resolve().parent==(root/'out/runs').resolve()
case=next(parent.glob('* Gui'));manifest=case/'gateway-host/manifest.json'
identity=json.loads(manifest.read_text())['run_id']
def health():
    with urlopen('http://127.0.0.1:8000/api/v1/health',timeout=3) as response:return json.load(response)
before=health();assert before['ready'] and before['run_id']==identity
spec=importlib.util.spec_from_file_location('port_environment',root/'scripts/g4_environment/manage.py')
environment=importlib.util.module_from_spec(spec);spec.loader.exec_module(environment)
python,_=environment.environment(root)
output=root/'out/runs'/('g4-t08-port-checks-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir()
child=subprocess.run([str(python),'-I','-B','-X','utf8',str(root/'apps/gis_gateway/server.py'),
    '--root',str(root),'--manifest',str(manifest),'--manifest-sha256',hashlib.sha256(manifest.read_bytes()).hexdigest(),
    '--output',str(output/'observer')],cwd=output,capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
(output/'stdout.log').write_bytes(child.stdout);(output/'stderr.log').write_bytes(child.stderr)
assert child.returncode!=0 and b'10048' in child.stderr and not (output/'observer').exists(),child.stderr
after=health();assert after['ready'] and after['run_id']==before['run_id'] and after['stream_id']==before['stream_id']
assert int(after['source_time_ms'])>=int(before['source_time_ms']) and not after['error']
result={'status':'passed','runId':output.name,'parentRunId':args.run_id,'duplicateExitCode':child.returncode,
        'refusedBeforeObserverStarted':True,'existingGatewayContinued':True,'before':before,'after':after,
        'sourceSHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(output.name+' passed')
