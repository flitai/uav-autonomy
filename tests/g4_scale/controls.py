from pathlib import Path
import importlib.util,json,sys,sqlite3,hashlib
from datetime import datetime
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'src'))
from sim_bridge.codec import load_schema,ProtocolError
from sim_bridge.journal import xml_object
import xml.etree.ElementTree as ET
def mod(name,path):
    s=importlib.util.spec_from_file_location(name,root/path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
run=root/'out/runs'/('g4-t08-controls-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));run.mkdir()
schema=load_schema(root)
old=root/'out/runs/g4-t08-diagnostic-20260920-082105-760256/中文 空格 Headless/uxas/datawork/SavedMessages/messageLog_1_0.db3'
with sqlite3.connect(old.as_uri()+'?mode=ro',uri=True) as db:
    node=ET.fromstring(db.execute('SELECT xml FROM msg WHERE id=203').fetchone()[0])
try:xml_object(node,schema)
except ProtocolError as e:
    assert str(e)=='XML array exceeds limit'
else:raise AssertionError('Original invalid CreateNewService accepted')
counts={n:len(node.find(n)) for n in ('EntityConfigurations','EntityStates')};assert set(counts.values())=={20}
coverage=mod('scale_coverage_controls','scripts/g4_scale/coverage.py')
parent=root/'out/runs/g4-t07-capture-20260920-025046-760714'; audit=root/'out/runs/g4-t07-audit-20260920-032048-023253'
results=[]
for name in ('point','line','area','mixed'):
    case=json.loads((parent/name/'case-result.json').read_text(encoding='utf-8-sig'))
    result=coverage.inspect(root,parent/name,case['scene']['assignments'])
    assert result==json.loads((audit/name/'statistics.json').read_text()),name
    results.append(name)
metrics=mod('scale_metrics_controls','scripts/g4_scale/metrics.py')
import os
memory=metrics.process(os.getpid());assert int(memory['private_bytes'])>0 and memory['cpu_seconds']>0
result={'status':'passed','runId':run.name,'oldCreateNewServiceRejected':counts,'optimizedReplayMatchesQualifiedT07':results,
        'metricsRealProcess':memory,'coverageSourceSHA256':hashlib.sha256((root/'scripts/g4_scale/coverage.py').read_bytes()).hexdigest()}
(run/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(result)
