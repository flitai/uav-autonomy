"""Bind G5-T08 recovery evidence to the qualified coverage display candidate."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import traceback

spec=__import__('importlib.util',fromlist=['']).spec_from_file_location('lifecycle_runtime',Path(__file__).with_name('runtime.py'))
r=__import__('importlib.util',fromlist=['']).module_from_spec(spec);spec.loader.exec_module(r)
c=r.c
ROOT=r.ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--baseline-run-id',required=True)
    parser.add_argument('--build-run-id',required=True)
    args=parser.parse_args()
    run=ROOT/'out/runs'/args.run_id
    record=dict(task='G5-T08',status='running',runId=args.run_id,lifecycleQualified=False)
    environment=dict(os.environ);location=Path.cwd()
    try:
        folder,binding,backend,mapdir,service,previous=c.qualify(args.baseline_run_id)
        candidate,manifest=c.candidate(args.build_run_id,binding)
        inputs=r.LifecycleRun.__new__(r.LifecycleRun).inputs()
        context=dict(binding=binding,inputs=inputs,baselineRunId=args.baseline_run_id,
                     configuration=str(ROOT/'config/g3-startup.json'),javaHome=str(ROOT/'.tools/jdk-11.0.32.1+1'),
                     terrainCandidate=str(backend),terrainCandidateSHA256=c.sha(backend/'candidate.json'),
                     buildRunId=backend.name,entityCandidate=str(candidate),stateCandidate=str(candidate))
        c.save(run/'context.json',context)
        command=[sys.executable,'-I','-B','-X','utf8',str(ROOT/'scripts/g5_lifecycle/runtime.py'),'--run-id',args.run_id]
        process=subprocess.run(command,cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
        runtime=c.load(run/'runtime-result.json')
        c.need(process.returncode==0 and runtime['status']=='passed' and runtime['lifecycleQualified'],'Lifecycle runtime failed')
        c.need(r.LifecycleRun.__new__(r.LifecycleRun).inputs()==inputs,'Lifecycle inputs changed')
        acceptance=dict(task='G5-T08',status='passed',buildRunId=args.build_run_id,
                        candidateSHA256=c.sha(candidate/'candidate.json'),binding=binding,inputs=inputs,
                        lifecycleQualified=True,stageQualified=False,cases=runtime['cases'])
        c.save(run/'acceptance.json',acceptance)
        record.update(status='passed',lifecycleQualified=True,stageQualified=False,inputs=inputs,
                      binding=binding,acceptanceSHA256=c.sha(run/'acceptance.json'))
        return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc())
        print(record['traceback'],flush=True)
        return 1
    finally:
        record.update(environmentUnchanged=environment==dict(os.environ),locationUnchanged=location==Path.cwd())
        c.save(run/'result.json',record)
        print('G5_T08_RESULT='+str(run/'result.json'),flush=True)


if __name__=='__main__':sys.exit(main())
