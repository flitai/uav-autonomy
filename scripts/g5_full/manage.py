"""Bind full original WaterwaySearch evidence to T08 and qualified G5 assets."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import traceback

spec=importlib.util.spec_from_file_location('full_runtime',Path(__file__).with_name('runtime.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
c=r.c
ROOT=r.ROOT

def main():
    parser=argparse.ArgumentParser()
    for name in ('run-id','baseline-run-id','build-run-id','lifecycle-run-id'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    run=ROOT/'out/runs'/args.run_id
    record=dict(task='G5-T09',runId=args.run_id,status='running',fullSimulationDisplayQualified=False)
    environment=dict(os.environ);location=Path.cwd()
    try:
        folder,binding,backend,mapdir,service,previous=c.qualify(args.baseline_run_id)
        candidate,manifest=c.candidate(args.build_run_id,binding)
        parent=ROOT/'out/runs'/args.lifecycle_run_id
        prior=c.load(parent/'acceptance.json')
        c.need(prior['task']=='G5-T08' and prior['status']=='passed' and prior['lifecycleQualified'] and
               prior['buildRunId']==args.build_run_id and
               prior['candidateSHA256']==c.sha(candidate/'candidate.json') and
               prior['binding']==binding,'T08 lifecycle evidence differs')
        for name in ('result.json','entry-result.json','runtime-result.json'):
            receipt=c.load(parent/name)
            c.need(receipt['status']=='passed','T08 '+name+' failed')
        c.need(c.load(parent/'result.json')['acceptanceSHA256'].lower()==
               c.sha(parent/'acceptance.json').lower(),'T08 receipt hash differs')
        c.base.verify_files(ROOT,prior['inputs'])
        source_probe=r.FullRun.__new__(r.FullRun);source_probe.root=ROOT
        inputs=source_probe.inputs()
        context=dict(binding=binding,inputs=inputs,baselineRunId=args.baseline_run_id,
                     configuration=str(ROOT/'config/g3-startup.json'),
                     executionConfiguration=str(ROOT/'config/g3-execution.json'),
                     completionConfiguration=str(ROOT/'config/g3-completion.json'),
                     javaHome=str(ROOT/'.tools/jdk-11.0.32.1+1'),
                     terrainCandidate=str(backend),terrainCandidateSHA256=c.sha(backend/'candidate.json'),
                     buildRunId=backend.name,entityCandidate=str(candidate),stateCandidate=str(candidate),
                     lifecycleRunId=args.lifecycle_run_id,
                     lifecycleAcceptanceSHA256=c.sha(parent/'acceptance.json'))
        c.save(run/'context.json',context)
        process=subprocess.run([sys.executable,'-I','-B','-X','utf8',
            str(ROOT/'scripts/g5_full/runtime.py'),'--run-id',args.run_id],
            cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
        runtime=c.load(run/'runtime-result.json')
        c.need(process.returncode==0 and runtime['status']=='passed' and
               runtime['fullSimulationDisplayQualified'],'Full original simulation failed')
        c.need(source_probe.inputs()==inputs,'T09 inputs changed')
        acceptance=dict(task='G5-T09',status='passed',buildRunId=args.build_run_id,
                        candidateSHA256=c.sha(candidate/'candidate.json'),binding=binding,inputs=inputs,
                        lifecycleRunId=args.lifecycle_run_id,
                        lifecycleAcceptanceSHA256=c.sha(parent/'acceptance.json'),
                        fullSimulationDisplayQualified=True,stageQualified=False,cases=runtime['cases'])
        c.save(run/'acceptance.json',acceptance)
        record.update(status='passed',fullSimulationDisplayQualified=True,stageQualified=False,
                      acceptanceSHA256=c.sha(run/'acceptance.json'),inputs=inputs,binding=binding)
        return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc())
        print(record['traceback'],flush=True);return 1
    finally:
        record.update(environmentUnchanged=environment==dict(os.environ),locationUnchanged=location==Path.cwd())
        c.save(run/'result.json',record)
        print('G5_T09_RESULT='+str(run/'result.json'),flush=True)

if __name__=='__main__':sys.exit(main())
