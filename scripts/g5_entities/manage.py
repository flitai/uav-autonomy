"""Build and qualify a composed Cesium entity viewer without rewriting predecessors."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

spec=__import__('importlib.util',fromlist=['']).spec_from_file_location('g5_entities_entry_common',Path(__file__).with_name('common.py'))
c=__import__('importlib.util',fromlist=['']).module_from_spec(spec);spec.loader.exec_module(c)
ROOT=c.ROOT

def build(run,folder,binding,backend,mapdir,mapservice,state_candidate,tool_package,chinese):
    directory=ROOT/'out/build/g5-entities'/run.name;directory.mkdir(parents=True)
    project=directory/('中文 空格实体页面' if chinese else 'project')
    shutil.copytree(ROOT/'apps/cesium_viewer',project,ignore=shutil.ignore_patterns('node_modules','dist'))
    # Dependencies stay in the qualified local T03 installation; no npm install.
    dependency=Path(mapservice['project'])/'node_modules'
    command="New-Item -ItemType Junction -Path '"+str(project/'node_modules').replace("'","''")+"' -Target '"+str(dependency).replace("'","''")+"' | Out-Null"
    c.invoke(['powershell.exe','-NoProfile','-Command',command],run,'dependency-junction')
    shutil.copytree(ROOT/'apps/cesium_state',project/'state')
    shutil.copytree(ROOT/'apps/cesium_entities',project/'entities')
    shutil.copytree(Path(mapservice['project'])/'public/fonts',project/'public/fonts',dirs_exist_ok=True)
    (project/'entry.ts').write_text("import './src/main';\nimport './entities/main';\n",encoding='utf-8')
    html=project/'index.html';html.write_text(html.read_text(encoding='utf-8').replace('/src/main.ts','/entry.ts'),encoding='utf-8')
    tsconfig=c.load(project/'tsconfig.json');tsconfig['include']=['src','state','entities','entry.ts'];c.save(project/'tsconfig.json',tsconfig)
    public=project/'public/entities';public.mkdir(parents=True)
    config=c.load(ROOT/'config/g5-entities.json');extracted=directory/'model-extracted';extracted.mkdir()
    env=dict(os.environ);env['PATH']=str(tool_package)+os.pathsep+env['PATH'];env['OSG_LIBRARY_PATH']=str(tool_package)
    c.invoke([tool_package/'g5-model-reader.exe',ROOT/config['model']['path'],extracted],run,'read-osgb',env=env)
    converter=c.module('g5_entities_convert',ROOT/'scripts/g5_models/convert.py')
    model=converter.convert(extracted,public/'ucav.glb',config['model']['metersPerUnit'])
    c.invoke([folder/'geo/Scripts/python.exe','-I','-B','-X','utf8',ROOT/'scripts/g5_entities/height.py',directory/'calibration'],run,'height-reference')
    height=c.load(directory/'calibration/height.json')
    entity_ids=set()
    for scene in ('original','small','mixed20'):
        info=c.load(backend/scene/'scene.json');entity_ids.update(str(a['entityId']) for a in info['assignments'])
    runtime=dict(schemaVersion=1,modelUrl='/entities/ucav.glb',modelName=config['model']['label'],modelLengthMeters=model['dimensionsMeters'][2],
        entityModels={k:'ucav' for k in sorted(entity_ids)},height=height,interpolationMilliseconds=config['interpolationMilliseconds'],modelSHA256=model['sha256'],affiliations=config['affiliations'])
    c.save(public/'runtime.json',runtime)
    state_service=c.load(state_candidate/'service.json');(project/'public/state').mkdir()
    shutil.copy2(Path(state_service['dist'])/'state/runtime.json',project/'public/state/runtime.json')
    node=folder/'node/node.exe';tsc=dependency/'typescript/bin/tsc'
    c.invoke([node,tsc,'--project',project/'tsconfig.json'],run,'typescript',cwd=project)
    c.invoke([node,dependency/'vite/bin/vite.js','build'],run,'vite-build',cwd=project,env=c.base.npm_env(ROOT,folder,project))
    dist=project/'dist';shutil.copytree(Path(mapservice['dist'])/'licenses',dist/'licenses')
    service=dict(mapservice,project=str(project),dist=str(dist));c.save(directory/'service.json',service)
    c.invoke([node,tsc,'--ignoreConfig','--target','ES2022','--module','NodeNext','--skipLibCheck','--outDir',project/'numerical',project/'entities/coordinates.ts'],run,'numerical-compile',cwd=project)
    java=ROOT/'.tools/jdk-11.0.32.1+1/bin';classes=directory/'calibration/classes';classes.mkdir()
    jar=ROOT/'out/artifacts/amase/OpenAMASE.jar'
    c.invoke([java/'javac.exe','-encoding','UTF-8','-cp',jar,'-d',classes,ROOT/'tests/g5_entities/PoseReference.java'],run,'pose-reference-compile')
    c.invoke([java/'java.exe','-cp',str(jar)+os.pathsep+str(classes),'PoseReference'],run,'pose-reference')
    shutil.copy2(run/'pose-reference.stdout',directory/'calibration/attitude-reference.json')
    c.invoke([node,ROOT/'tests/g5_entities/numerical.mjs',project,directory/'calibration',run/'numerical.json'],run,'numerical')
    c.invoke([node,tsc,'--ignoreConfig','--target','ES2022','--module','NodeNext','--skipLibCheck','--outDir',project/'layer-unit',project/'entities/layer.ts'],run,'layer-unit-compile',cwd=project)
    c.invoke([node,ROOT/'tests/g5_entities/lifecycle.mjs',project,run/'lifecycle.json'],run,'entity-lifecycle')
    c.invoke([sys.executable,'-I','-B','-X','utf8',ROOT/'tests/g5_entities/model.py',extracted,public/'ucav.glb',run/'model.json'],run,'model-audit')
    c.save(directory/'model-source.json',dict(original=config['model'],toolManifestSHA256=binding['modelTools']['manifestSHA256'],conversion=model))
    files=[p for p in directory.rglob('*') if p.is_file() and 'node_modules' not in p.parts]
    manifest=dict(task='G5-T06',buildRunId=run.name,inputs=c.sources(),binding=binding,files=c.base.inventory(directory,files),stageQualified=False)
    c.save(directory/'candidate.json',manifest)
    return directory

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--action',choices=['build','test','session'],required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--baseline-run-id',required=True);parser.add_argument('--build-run-id');parser.add_argument('--chinese-path',action='store_true');parser.add_argument('--mode',choices=['Gui','Headless'],default='Gui');a=parser.parse_args()
    run=ROOT/'out/runs'/a.run_id;record=dict(task='G5-T06',status='running',runId=a.run_id,action=a.action,stageQualified=False)
    environment=dict(os.environ);location=Path.cwd()
    try:
        folder,binding,backend,mapdir,service,state_candidate,package=c.qualify(a.baseline_run_id);inputs=c.sources()
        context=dict(binding=binding,inputs=inputs,baselineRunId=a.baseline_run_id,configuration=str(ROOT/'config/g3-startup.json'),javaHome=str(ROOT/'.tools/jdk-11.0.32.1+1'),terrainCandidate=str(backend),terrainCandidateSHA256=c.sha(backend/'candidate.json'),buildRunId=backend.name)
        if a.action=='build':
            directory=build(run,folder,binding,backend,mapdir,service,state_candidate,package,a.chinese_path)
            record['candidateSHA256']=c.sha(directory/'candidate.json')
        else:
            directory,manifest=c.candidate(a.build_run_id,binding);context.update(entityCandidate=str(directory),stateCandidate=str(directory))
            c.save(run/'context.json',context)
            command=[sys.executable,'-I','-B','-X','utf8',str(ROOT/'scripts/g5_entities/runtime.py'),'--run-id',a.run_id]
            if a.action=='session':command+=['--session','--mode',a.mode]
            process=subprocess.run(command,cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
            runtime=c.load(run/'runtime-result.json');c.need(process.returncode==0 and runtime['status']=='passed','Entity runtime failed')
            if a.action=='test':
                c.save(run/'acceptance.json',dict(task='G5-T06',status='passed',buildRunId=a.build_run_id,validationRunId=a.run_id,candidateSHA256=c.sha(directory/'candidate.json'),binding=binding,inputs=inputs,
                    entityDisplayQualified=True,stageQualified=False,cases=runtime['cases'],resourceChecks=runtime['resourceChecks']))
                record['acceptanceSHA256']=c.sha(run/'acceptance.json')
        c.need(c.sources()==inputs,'T06 sources changed during operation');record.update(status='passed',inputs=inputs,binding=binding);return 0
    except Exception as error:record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(record['traceback']);return 1
    finally:
        record.update(environmentUnchanged=environment==dict(os.environ),locationUnchanged=location==Path.cwd())
        if not record['environmentUnchanged'] or not record['locationUnchanged']:record['status']='failed'
        c.save(run/'result.json',record);print('G5_T06_RESULT='+str(run/'result.json'))
if __name__=='__main__':sys.exit(main())
