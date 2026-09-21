"""Windows build/serve/real-browser acceptance for the read-only Cesium state module."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

spec=__import__('importlib.util',fromlist=['']).spec_from_file_location('g5_state_entry_common',Path(__file__).with_name('common.py'))
c=__import__('importlib.util',fromlist=['']).module_from_spec(spec);spec.loader.exec_module(c)
ROOT=c.ROOT

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--action',choices=['build','serve','test','session'],required=True)
    parser.add_argument('--run-id',required=True);parser.add_argument('--baseline-run-id',required=True);parser.add_argument('--build-run-id')
    parser.add_argument('--chinese-path',action='store_true');parser.add_argument('--mode',choices=['Gui','Headless'],default='Gui');args=parser.parse_args()
    run=ROOT/'out/runs'/args.run_id;c.need(run.is_dir() and not (run/'result.json').exists(),'Fresh run required')
    record=dict(task='G5-T05',runId=args.run_id,status='running',action=args.action,stageQualified=False,startedAt=time.time())
    before=dict(os.environ);location=Path.cwd()
    try:
        folder,binding,backend,mapdir,service=c.qualify(args.baseline_run_id);inputs=c.sources(ROOT)
        context=dict(binding=binding,inputs=inputs,baselineRunId=args.baseline_run_id,
            configuration=str(ROOT/'config/g3-startup.json'),javaHome=str(ROOT/'.tools'/next(x['installDirectory'] for x in c.load(ROOT/'config/windows-java-toolchain.json')['tools'] if x['id']=='jdk')),
            terrainCandidate=str(backend),terrainCandidateSHA256=c.sha(backend/'candidate.json'),buildRunId=backend.name)
        c.save(run/'context.json',context)
        if args.action=='build':
            directory=ROOT/'out/build/g5-state'/args.run_id;directory.mkdir(parents=True)
            project=directory/('中文 空格页面' if args.chinese_path else 'project');project.mkdir()
            dist=project/'dist';shutil.copytree(Path(service['dist']),dist)
            source=project/'source';shutil.copytree(ROOT/'apps/cesium_state',source)
            compiler=Path(service['project'])/'node_modules/typescript/bin/tsc'
            c.invoke([folder/'node/node.exe',compiler,'--project',source/'tsconfig.json','--outDir',dist/'state'],run,'typescript',timeout=120)
            config=c.load(ROOT/'config/g5-state.json')
            c.save(dist/'state/runtime.json',dict(schemaVersion=1,protocolVersion=1,limits=config['limits'],terrain=dict(datum='EPSG:5773',binding=binding['backendTerrain']),geography=binding['geography']))
            html=dist/'index.html';text=html.read_text(encoding='utf-8');c.need(text.count('</body>')==1,'Unexpected map entry')
            html.write_text(text.replace('</body>','<script type="module" src="/state/main.js"></script></body>'),encoding='utf-8')
            service['dist']=str(dist);service['project']=str(project);c.save(directory/'service.json',service)
            c.invoke([folder/'node/node.exe',ROOT/'tests/g5_state/reducer.mjs',dist/'state',run/'reducer.json'],run,'reducer',timeout=60)
            manifest=dict(task='G5-T05',buildRunId=args.run_id,inputs=inputs,binding=binding,stageQualified=False,
                files=c.base.inventory(directory,[p for p in directory.rglob('*') if p.is_file()]),mapAssetsReused=True)
            c.save(directory/'candidate.json',manifest);record['candidateSHA256']=c.sha(directory/'candidate.json')
        else:
            directory,manifest=c.candidate(args.build_run_id,binding)
            context.update(stateCandidate=str(directory),stateCandidateSHA256=c.sha(directory/'candidate.json'))
            c.save(run/'context.json',context)
            if args.action=='serve':
                print('G5_STATE_STOP_FILE='+str(run/'request-stop'),flush=True)
                c.invoke([folder/'node/node.exe',ROOT/'scripts/g5_state/server.mjs',directory/'service.json',run],run,'service',timeout=None)
                c.need(c.load(run/'server-result.json')['normalExit'],'Service exit failed')
            elif args.action=='session':
                print('G5_STATE_STOP_FILE='+str(run/'request-stop'),flush=True)
                process=subprocess.run([sys.executable,'-I','-B','-X','utf8',str(ROOT/'scripts/g5_state/runtime.py'),'--run-id',args.run_id,'--session','--mode',args.mode],cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
                runtime=c.load(run/'runtime-result.json');c.need(process.returncode==0 and runtime['status']=='passed','State session failed')
            else:
                c.invoke([folder/'node/node.exe',ROOT/'tests/g5_state/reducer.mjs',Path(c.load(directory/'service.json')['dist'])/'state',run/'reducer.json'],run,'reducer',timeout=60)
                process=subprocess.run([sys.executable,'-I','-B','-X','utf8',str(ROOT/'scripts/g5_state/runtime.py'),'--run-id',args.run_id],cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
                runtime=c.load(run/'runtime-result.json');c.need(process.returncode==0 and runtime['status']=='passed','Real browser qualification failed')
                c.save(run/'acceptance.json',dict(task='G5-T05',status='passed',buildRunId=args.build_run_id,validationRunId=args.run_id,
                    candidateSHA256=c.sha(directory/'candidate.json'),binding=binding,realStateConnectionQualified=True,simulationDisplayQualified=False,stageQualified=False,
                    cases=runtime['cases'],inputs=inputs))
                record['acceptanceSHA256']=c.sha(run/'acceptance.json')
        c.base.verify_files(ROOT,inputs);record.update(status='passed',inputs=inputs,binding=binding)
        return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(record['traceback'],flush=True);return 1
    finally:
        record.update(finishedAt=time.time(),environmentUnchanged=before==dict(os.environ),locationUnchanged=location==Path.cwd())
        if not record['environmentUnchanged'] or not record['locationUnchanged']:record['status']='failed'
        c.save(run/'result.json',record);print('G5_T05_RESULT='+str(run/'result.json'),flush=True)

if __name__=='__main__':sys.exit(main())
