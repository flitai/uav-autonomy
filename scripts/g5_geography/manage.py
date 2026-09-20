"""Native entry: bind current backend and isolated G5 tools before data work."""
import argparse
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g5_environment'))
from common import environment, inventory, invoke, load, need, save, sha, upstream, verify_files


def inputs(root):
    paths=[p for folder in ('scripts/g5_geography','tests/g5_geography') for p in (root/folder).rglob('*')
           if p.is_file() and '__pycache__' not in p.parts]
    paths += [root/p for p in ('config/g5-terrain.json','config/g5-geography-lock.json',
        'config/g5-regional-sources.json','config/g5-usgs-operation.json','config/g5-terrarium-legacy.json',
        'scripts/windows/prepare-g5-geography.ps1','scripts/windows/g5-geography-common.ps1','tests/windows/g5-geography.tests.ps1')]
    return inventory(root,paths)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);parser.add_argument('--baseline-run-id',required=True)
    parser.add_argument('--action',choices=['prepare','test'],required=True);parser.add_argument('--build-run-id')
    args=parser.parse_args();root=ROOT;run=root/'out/runs'/args.run_id
    record=dict(task='G5-T02',runId=args.run_id,action=args.action,status='running',startedAt=time.time(),
                simulationStarted=False,stageQualified=False,inputs=inputs(root))
    try:
        need(run.is_dir() and run.resolve().is_relative_to(root/'out/runs') and not (run/'result.json').exists(),'Invalid run identity')
        folder,manifest=environment(root);record['environment']=load(root/'.tools/g5/current.json')
        record['upstream']=upstream(root,args.baseline_run_id)
        save(run/'context.json',record)
        arguments=[folder/'geo/Scripts/python.exe','-I','-B','-X','utf8',root/'scripts/g5_geography/worker.py',
                   '--root',root,'--run-id',args.run_id,'--action',args.action]
        if args.build_run_id:arguments+=['--build-run-id',args.build_run_id]
        invoke(arguments,run,'geography',cwd=run,timeout=1800)
        outcome=load(run/'worker-result.json');need(outcome['status']=='passed','Geography worker failed')
        verify_files(root,record['inputs'])
        need(record['environment']==load(root/'.tools/g5/current.json'),'Environment pointer changed')
        record.update(status='passed',outcome=outcome)
    except BaseException as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc());raise
    finally:save(run/'result.json',record)


if __name__=='__main__':main()
