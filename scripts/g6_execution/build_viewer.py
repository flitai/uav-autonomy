"""Build an independent B04 viewer candidate from the qualified B03 project."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g6_release'))
import manage as release

def need(value,message):
    if not value:raise RuntimeError(message)

def command(args,folder,label,cwd=None,env=None):
    done=subprocess.run([str(v) for v in args],cwd=cwd or ROOT,env=env,
                        capture_output=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
    (folder/(label+'.stdout')).write_bytes(done.stdout)
    (folder/(label+'.stderr')).write_bytes(done.stderr)
    need(done.returncode==0,label+' failed')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True)
    args=parser.parse_args();need(args.run_id.startswith('g6-b04-build-'),'B04 build ID required')
    run=ROOT/'out/runs'/args.run_id;build=ROOT/'out/build/g6-execution'/args.run_id
    need(not run.exists() and not build.exists(),'B04 build ID exists')
    run.mkdir(parents=True);build.mkdir(parents=True)
    record=dict(task='G6-B04',runId=args.run_id,status='running',executionQualified=False)
    try:
        parent_id='g6-b03-build-20260924-2438'
        parent_receipt=ROOT/'out/runs'/parent_id/'result.json'
        parent=release.load(parent_receipt)
        need(parent['status']=='passed' and parent['task']=='G6-B03','B03 qualified build missing')
        for row in parent['inputs']:
            need(release.digest(ROOT/row['path']).lower()==row['sha256'].lower(),
                 'B03 input changed: '+row['path'])
        source=ROOT/'out/build/g6-drafts'/parent_id/'project'
        project=build/'project'
        shutil.copytree(source,project,ignore=shutil.ignore_patterns('node_modules','dist'))
        dependency=source/'node_modules'
        need((dependency/'typescript/bin/tsc').is_file(),'B03 dependency unavailable')
        command(['powershell.exe','-NoProfile','-Command',
                 "New-Item -ItemType Junction -Path '"+str(project/'node_modules').replace("'","''")+
                 "' -Target '"+str(dependency.resolve()).replace("'","''")+"' | Out-Null"],
                run,'dependency-junction')
        shutil.copytree(ROOT/'apps/cesium_execution',project/'execution')
        entry=project/'entities/main.ts';source_text=entry.read_text(encoding='utf-8')
        source_text="import { ExecutionPanel } from '../execution/panel';\n"+source_text
        anchor='  const taskPanel=new TaskPanel(viewer,missions.model.heights);'
        need(source_text.count(anchor)==1,'B03 viewer init changed')
        source_text=source_text.replace(anchor,anchor+'\n  const executionPanel=new ExecutionPanel();')
        anchor='taskPanel.destroy();control.destroy();coverage?.destroy();'
        need(source_text.count(anchor)==1,'B03 viewer cleanup changed')
        source_text=source_text.replace(anchor,'executionPanel.destroy();'+anchor)
        entry.write_text(source_text,encoding='utf-8')
        tsconfig=release.load(project/'tsconfig.json');tsconfig['include'].append('execution')
        release.save(project/'tsconfig.json',tsconfig)
        node=ROOT/release.load(ROOT/'.tools/g5/current.json')['path']/'node/node.exe'
        command([node,dependency/'typescript/bin/tsc','--project',project/'tsconfig.json'],
                run,'typescript',cwd=project)
        env=dict(os.environ);env['PATH']=str(node.parent)+os.pathsep+env['PATH']
        command([node,dependency/'vite/bin/vite.js','build'],run,'vite-build',cwd=project,env=env)
        service=release.load(ROOT/'out/build/g6-drafts'/parent_id/'service.json')
        service.update(dist=str(project/'dist'),project=str(project))
        release.save(build/'service.json',service)
        inputs=[ROOT/path for path in ('apps/cesium_execution/panel.ts','apps/cesium_execution/style.css',
                'apps/g6_execution/server.py','scripts/g6_execution/core.py',
                'scripts/g6_execution/build_viewer.py')]
        record.update(status='passed',b03BuildRunId=parent_id,
                      b03BuildSHA256=release.digest(parent_receipt),
                      inputs=[dict(path=p.relative_to(ROOT).as_posix(),sha256=release.digest(p)) for p in inputs],
                      service=str(build/'service.json'),dist=str(project/'dist'))
        return 0
    except Exception as error:
        record.update(status='failed',error=str(error));print(error,file=sys.stderr)
        return 1
    finally:release.save(run/'result.json',record)

if __name__=='__main__':sys.exit(main())
