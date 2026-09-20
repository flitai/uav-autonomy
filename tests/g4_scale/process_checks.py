"""Prove sampling includes the actual interpreter behind a Windows venv launcher."""
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,root/path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
metrics=module('scale_process_metrics','scripts/g4_scale/metrics.py')
env=module('scale_process_environment','scripts/g4_environment/manage.py')
python,_=env.environment(root)
code='import os,sys; allocation=bytearray(32*1024*1024); print(os.getpid(),flush=True); sys.stdin.readline()'
child=subprocess.Popen([str(python),'-I','-B','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                       text=True,creationflags=subprocess.CREATE_NO_WINDOW)
try:
    interpreter=int(child.stdout.readline().strip())
    group=metrics.process_group(child.pid,metrics.process_parents())
    assert interpreter!=child.pid and str(interpreter) in {r['pid'] for r in group['members']}
    actual=next(row for row in group['members'] if row['pid']==str(interpreter))
    assert int(actual['private_bytes'])>=32*1024*1024 and int(group['private_bytes'])>=int(actual['private_bytes'])
finally:
    child.communicate('\n',timeout=10)
assert child.returncode==0
output=root/'out/runs'/('g4-t08-process-checks-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir()
result={'status':'passed','launcherPID':str(child.pid),'actualInterpreterPID':str(interpreter),
        'ownedTree':group,'normalExitCode':child.returncode,'metricsSHA256':env.sha(root/'scripts/g4_scale/metrics.py')}
env.save(output/'result.json',result);print(output.name)
