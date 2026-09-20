"""Startup samples and strict provenance for an offline-only audit correction."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

root=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
performance=module('corrected_performance',root/'scripts/g4_scale/performance.py')
audit=module('corrected_audit',root/'scripts/g4_scale/audit.py')
receipt=audit.load(root/'out/runs/g4-t08-capture-20260920-085508-125483/result.json')
revisions=audit.capture_sources(root,receipt)
assert {r['path'] for r in revisions}=={'scripts/g4_scale/audit.py','scripts/g4_scale/performance.py'}
intervals=performance.sample_intervals([(0,10),(2040,10.2),(2540,10.7),(3080,11.24)])
assert intervals=={'initialSnapshotToDynamicMilliseconds':'2040','maximumDynamicIntervalMilliseconds':'540','dynamicSpanMilliseconds':'1040'}
checks=['initial-snapshot-separated','only-offline-source-revisions','execution-statistics-functions-unchanged']
def reject(name,action):
    try:action()
    except ValueError:checks.append(name)
    else:raise AssertionError(name)
reject('real-dynamic-gap',lambda:performance.sample_intervals([(0,0),(2040,2),(5041,5)]))
reject('duplicate-zero-sample',lambda:performance.sample_intervals([(0,0),(0,.1),(2040,2)]))
reject('missing-initial-snapshot',lambda:performance.sample_intervals([(10,0),(2040,2),(2540,2.5)]))
bad=deepcopy(receipt)
next(r for r in bad['inputs'] if r['path']=='src/sim_bridge/gateway.py')['sha256']='0'*64
reject('runtime-change-not-allowed',lambda:audit.capture_sources(root,bad))
bad=deepcopy(receipt)
next(r for r in bad['inputs'] if r['path']=='scripts/g4_scale/performance.py')['sha256']='0'*64
reject('unknown-audit-predecessor',lambda:audit.capture_sources(root,bad))
output=root/'out/runs'/('g4-t08-audit-revision-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir()
result={'status':'passed','runId':output.name,'checks':checks,'offlineSourceCorrections':revisions,
    'sourceSHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
