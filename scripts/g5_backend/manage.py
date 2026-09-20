"""Windows prepare/run/independent-acceptance entry for G5-T04."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('backend_entry_common',Path(__file__).with_name('common.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

def candidate(identity,binding):
    c.need(identity and re.fullmatch(r'g5-t04-prepare-[a-z0-9-]+',identity),'Explicit terrain preparation identity required')
    previous=ROOT/'out/runs'/identity
    c.need(c.load(previous/'result.json')['status']==c.load(previous/'entry-result.json')['status']=='passed','Preparation did not pass')
    directory=ROOT/'out/build/g5-backend'/identity
    manifest=c.load(directory/'candidate.json')
    c.need(c.load(previous/'result.json')['candidateSHA256']==c.sha(directory/'candidate.json'),'Candidate receipt changed')
    c.need(manifest['inputs']==c.sources(ROOT) and c.stable(manifest['binding'])==c.stable(binding),'T04 candidate source or upstream changed; prepare again')
    c.base.verify_files(ROOT,manifest['inputs']);c.base.verify_files(directory,manifest['files'])
    return directory,manifest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--action',choices=['prepare','run','test'],required=True)
    parser.add_argument('--run-id',required=True);parser.add_argument('--baseline-run-id',required=True)
    parser.add_argument('--build-run-id');parser.add_argument('--flight-run-id');parser.add_argument('--modes',nargs='+',default=['Headless','Gui'],choices=['Headless','Gui'])
    args=parser.parse_args();run=ROOT/'out/runs'/args.run_id
    c.need(re.fullmatch(r'g5-t04-[a-z0-9-]+',args.run_id) and run.is_dir() and not (run/'result.json').exists(),'Fresh entry run required')
    record=dict(schemaVersion=1,task='G5-T04',action=args.action,runId=args.run_id,status='running',stageQualified=False,startedAt=time.time())
    before=dict(os.environ);location=Path.cwd()
    try:
        folder,geography,binding=c.qualify(ROOT,args.baseline_run_id)
        inputs=c.sources(ROOT)
        context=dict(binding=binding,inputs=inputs,baselineRunId=args.baseline_run_id,
            configuration=str(ROOT/'config/g3-startup.json'),
            javaHome=str(ROOT/'.tools'/next(x['installDirectory'] for x in c.load(ROOT/'config/windows-java-toolchain.json')['tools'] if x['id']=='jdk')))
        c.save(run/'context.json',context)
        if args.action=='prepare':
            output=ROOT/'out/build/g5-backend'/args.run_id
            c.invoke([folder/'geo/Scripts/python.exe','-I','-B','-X','utf8',ROOT/'scripts/g5_backend/prepare.py',
                '--geography',geography,'--output',output],run,'scene-prepare',timeout=180)
            checks=c.module('g5_backend_independent_prepare',ROOT/'tests/g5_backend/checks.py')
            evidence=checks.prepared(ROOT,output);c.save(run/'scene-checks.json',evidence)
            manifest=dict(schemaVersion=1,task='G5-T04',buildRunId=args.run_id,inputs=inputs,binding=binding,
                files=c.base.inventory(output,[p for p in output.rglob('*') if p.is_file()]),
                scenePreparationQualified=True,backendTerrainExecutionQualified=False,stageQualified=False)
            c.save(output/'candidate.json',manifest)
            record.update(candidate=output.relative_to(ROOT).as_posix(),candidateSHA256=c.sha(output/'candidate.json'))
        else:
            directory,manifest=candidate(args.build_run_id,binding)
            context.update(terrainCandidate=str(directory),terrainCandidateSHA256=c.sha(directory/'candidate.json'),buildRunId=args.build_run_id)
            c.save(run/'context.json',context)
            if args.action=='run':
                process=subprocess.run([sys.executable,'-I','-B','-X','utf8',str(ROOT/'scripts/g5_backend/runtime.py'),
                    '--run-id',args.run_id,'--modes',*args.modes],cwd=ROOT,env=c.base.process_env(),creationflags=subprocess.CREATE_NO_WINDOW)
                record=c.load(run/'result.json')
                c.need(process.returncode==0 and record['status']=='passed','Terrain flight failed; see case-result.json')
            else:
                checks=c.module('g5_backend_independent_acceptance',ROOT/'tests/g5_backend/checks.py')
                evidence=checks.accept(ROOT,directory,args.flight_run_id,run)
                c.save(run/'acceptance.json',dict(schemaVersion=1,task='G5-T04',status='passed',buildRunId=args.build_run_id,
                    flightRunId=args.flight_run_id,validationRunId=args.run_id,binding=binding,
                    candidateSHA256=c.sha(directory/'candidate.json'),backendTerrainExecutionQualified=True,
                    stageQualified=False,evidence=evidence))
                record.update(backendTerrainExecutionQualified=True,acceptanceSHA256=c.sha(run/'acceptance.json'))
        c.base.verify_files(ROOT,inputs)
        c.need(before==dict(os.environ) and location==Path.cwd(),'Entry environment changed')
        record.update(status='passed',binding=binding,inputs=inputs,inputsUnchanged=True)
        return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc())
        print('G5-T04 failed: '+str(error),flush=True);return 1
    finally:
        record['finishedAt']=time.time();c.save(run/'result.json',record)
        print('G5_T04_RESULT='+str(run/'result.json'),flush=True)

if __name__=='__main__':sys.exit(main())
