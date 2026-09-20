"""Run existing state, journal-refusal and publication checks after scale fixes."""
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'src'))
from sim_bridge.codec import load_schema
output=root/'out/runs'/('g4-t08-regression-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir()
sources=[Path(__file__),root/'tests/g4_state/checks.py',root/'tests/g4_recovery/checks.py',root/'tests/g4_web/publication_checks.py']
sources+=sorted((root/'src/sim_bridge').glob('*.py'))
record={'status':'running','runId':output.name,'checks':{},'realTaskExecutionClaimed':False,
        'sources':[{'path':p.relative_to(root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources]}
try:
    for name,args in [('state',(root,output/'state')),('recovery',(root,output/'recovery',load_schema(root))),('publication',(output/'publication',))]:
        index={'state':1,'recovery':2,'publication':3}[name]
        spec=importlib.util.spec_from_file_location('scale_regression_'+name,sources[index])
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        record['checks'][name]=module.verify(*args)
    record['status']='passed'
except Exception as error:record.update(status='failed',error=str(error),traceback=traceback.format_exc())
finally:
    (output/'result.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record))
sys.exit(0 if record['status']=='passed' else 1)
