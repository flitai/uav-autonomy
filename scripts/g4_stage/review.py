"""Independent immutable pre-close proof; does not claim normal exit."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
package=module('review_package',Path(__file__).with_name('package.py'))
load,save,sha,need=package.load,package.save,package.sha,package.need


def prefix(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    remaining=source.stat().st_size
    with source.open('rb') as stream,target.open('xb') as output:
        while remaining:
            data=stream.read(min(1024*1024,remaining)); need(data,'Live prefix truncated')
            output.write(data); remaining-=len(data)
    if target.suffix=='.jsonl':
        with target.open('r+b') as stream:
            size=stream.seek(0,2); start=max(0,size-1048576); stream.seek(start); tail=stream.read()
            end=tail.rfind(b'\n'); need(end>=0,'Incomplete JSONL prefix'); stream.truncate(start+end+1)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True); args=parser.parse_args()
    directory=args.directory; output=directory/'review'; output.mkdir()
    evidence=output/'evidence'; evidence.mkdir()
    case=load(directory/'preclose-case.json')
    for name in ('observer.jsonl','amase.jsonl','amase/events.jsonl','amase/analysis.xml','amase/coverage-cells.xml','amase/analysis-events.tsv'):
        prefix(directory/name,evidence/name)
    for path in (directory/'amase').glob('execution-*.jsonl'): prefix(path,evidence/'amase'/path.name)
    shutil.copytree(directory/'scene',evidence/'scene')
    execution=module('stage_mixed_execution',args.root/'scripts/g4_mixed/execution.py')
    coverage=module('stage_mixed_coverage',args.root/'scripts/g4_scale/coverage.py')
    def rows(path):
        with path.open(encoding='utf-8') as source: return [json.loads(line) for line in source]
    requests={row['taskId']:ET.parse(evidence/'scene'/row['requestFile']).getroot() for row in case['scene']['assignments']}
    proof=execution.assess(args.root,rows(evidence/'observer.jsonl'),rows(evidence/'amase.jsonl'),rows(evidence/'amase/events.jsonl'),
        [row for path in sorted((evidence/'amase').glob('execution-*.jsonl')) for row in rows(path)],case['scene']['assignments'],requests)
    statistics=coverage.inspect(args.root,evidence,case['scene']['assignments'])
    save(output/'execution.json',proof); save(output/'statistics.json',statistics)
    snapshot=load(directory/'completed-scene.json')
    need(len(proof['tasks'])==20 and len(snapshot['state']['tasks'])==20,'Final twenty task proof missing')
    for task in proof['tasks']:
        state=snapshot['state']['tasks'][task['taskId']]
        need(state['backend_completed'] and state['completed_entity_ids']==[task['entityId']] and
             state['completed_time_ms']==task['completedTimeMs'],'Reviewed completion differs')
    clients=load(directory/'continuous-clients/result.json')
    need(clients['status']=='passed' and len(clients['clients'])==3,'Final clients incomplete')
    for index in range(3): need(load(directory/'continuous-clients'/('final-'+str(index)+'.json'))==case['clientFinalBoundary'],'Client boundary differs')
    save(output/'review.json',dict(status='passed',taskExecutionValidated=True,taskCompletionValidated=True,coverageValidated=True,
        taskCount=20,normalExitValidated=False,manualGuiAcceptance=False,clientFinalBoundary=case['clientFinalBoundary'],
        files=package.files(output,[p for p in output.rglob('*') if p.is_file()])))
    return 0


if __name__=='__main__': sys.exit(main())
