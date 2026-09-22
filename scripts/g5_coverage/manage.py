"""Build/validate the independently bound reconnaissance display supplement."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

spec=__import__('importlib.util',fromlist=['']).spec_from_file_location('coverage_common',Path(__file__).with_name('common.py'))
c=__import__('importlib.util',fromlist=['']).module_from_spec(spec);spec.loader.exec_module(c)
ROOT=c.ROOT

def build(run,folder,binding,backend,map_service,previous,chinese):
    directory=ROOT/'out/build/g5-coverage'/run.name;directory.mkdir(parents=True)
    project=directory/('中文 空格侦察页面' if chinese else 'project');service=c.load(previous/'service.json')
    shutil.copytree(service['project'],project,ignore=shutil.ignore_patterns('node_modules','dist','layer-unit','mission-unit','coverage-unit','numerical'))
    dependency=Path(map_service['project'])/'node_modules'
    command="New-Item -ItemType Junction -Path '"+str(project/'node_modules').replace("'","''")+"' -Target '"+str(dependency).replace("'","''")+"' | Out-Null"
    c.invoke(['powershell.exe','-NoProfile','-Command',command],run,'dependency-junction')
    shutil.copytree(ROOT/'apps/cesium_coverage',project/'coverage')
    path=project/'entities/main.ts';text=path.read_text(encoding='utf-8')
    text="import { CoveragePanel } from '../coverage/ui';\n"+text
    for old,new in [
        ('let missions:MissionPanel|undefined;','let missions:MissionPanel|undefined;let coverage:CoveragePanel|undefined;'),
        ('missions?.update();','missions?.update();coverage?.update();'),
        ('missions=await MissionPanel.create(viewer,connection,layer,config);','missions=await MissionPanel.create(viewer,connection,layer,config);\n  coverage=new CoveragePanel(viewer,connection,layer,missions.model.heights);'),
        ('missions?.destroy();connection.stop();','coverage?.destroy();missions?.destroy();connection.stop();')]:
        c.need(text.count(old)==1,'T07 composition anchor differs: '+old);text=text.replace(old,new)
    path.write_text(text,encoding='utf-8');cfg=c.load(project/'tsconfig.json');cfg['include'].append('coverage');c.save(project/'tsconfig.json',cfg)
    node=folder/'node/node.exe';tsc=dependency/'typescript/bin/tsc'
    c.invoke([node,tsc,'--project',project/'tsconfig.json'],run,'typescript',cwd=project)
    c.invoke([node,dependency/'vite/bin/vite.js','build'],run,'vite-build',cwd=project,env=c.base.npm_env(ROOT,folder,project))
    shutil.copytree(Path(service['dist'])/'licenses',project/'dist/licenses')
    c.save(directory/'service.json',dict(service,project=str(project),dist=str(project/'dist')))
    c.invoke([node,tsc,'--ignoreConfig','--target','ES2022','--module','NodeNext','--skipLibCheck','--outDir',project/'coverage-unit',project/'coverage/geometry.ts'],run,'coverage-unit-compile',cwd=project)
    c.invoke([sys.executable,'-I','-B','-X','utf8',ROOT/'tests/g5_coverage/checks.py','--output',run/'engine-tests','--terrain',backend],run,'engine-tests')
    c.invoke([node,ROOT/'tests/g5_coverage/geometry.mjs',project,run/'geometry.json'],run,'geometry-tests')
    c.save(directory/'candidate.json',dict(task='G5-Coverage',buildRunId=run.name,inputs=c.sources(),binding=binding,files=c.base.inventory(directory,[p for p in directory.rglob('*') if p.is_file() and 'node_modules' not in p.parts]),stageQualified=False))
    return directory

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--action',choices=['build','test','session'],required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--baseline-run-id',required=True);parser.add_argument('--build-run-id');parser.add_argument('--chinese-path',action='store_true');parser.add_argument('--mode',choices=['Gui','Headless'],default='Gui');a=parser.parse_args()
    run=ROOT/'out/runs'/a.run_id;record=dict(task='G5-Coverage',status='running',runId=a.run_id,action=a.action,stageQualified=False)
    environment=dict(os.environ);location=Path.cwd()
    try:
        folder,binding,backend,mapdir,service,previous=c.qualify(a.baseline_run_id);inputs=c.sources()
        context=dict(binding=binding,inputs=inputs,baselineRunId=a.baseline_run_id,configuration=str(ROOT/'config/g3-startup.json'),javaHome=str(ROOT/'.tools/jdk-11.0.32.1+1'),terrainCandidate=str(backend),terrainCandidateSHA256=c.sha(backend/'candidate.json'),buildRunId=backend.name)
        if a.action=='build':
            directory=build(run,folder,binding,backend,service,previous,a.chinese_path);record['candidateSHA256']=c.sha(directory/'candidate.json')
        else:
            directory,manifest=c.candidate(a.build_run_id,binding);context.update(entityCandidate=str(directory),stateCandidate=str(directory));c.save(run/'context.json',context)
            command=[sys.executable,'-I','-B','-X','utf8',str(ROOT/'scripts/g5_coverage/runtime.py'),'--run-id',a.run_id]
            if a.action=='session':command+=['--session','--mode',a.mode]
            process=subprocess.run(command,cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
            runtime=c.load(run/'runtime-result.json');c.need(process.returncode==0 and runtime['status']=='passed','Coverage runtime failed')
            if a.action=='test':
                c.save(run/'acceptance.json',dict(task='G5-Coverage',status='passed',buildRunId=a.build_run_id,candidateSHA256=c.sha(directory/'candidate.json'),binding=binding,inputs=inputs,coverageDisplayQualified=True,stageQualified=False,cases=runtime['cases'],resourceChecks=runtime['resourceChecks']))
                record['acceptanceSHA256']=c.sha(run/'acceptance.json')
        c.need(c.sources()==inputs,'Coverage inputs changed during operation');record.update(status='passed',inputs=inputs,binding=binding);return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(record['traceback']);return 1
    finally:
        record.update(environmentUnchanged=environment==dict(os.environ),locationUnchanged=location==Path.cwd())
        c.save(run/'result.json',record);print('G5_COVERAGE_RESULT='+str(run/'result.json'))
if __name__=='__main__':sys.exit(main())
