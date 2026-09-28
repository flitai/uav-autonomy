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

def replace_one(path, before, after):
    source=path.read_text(encoding='utf-8')
    need(source.count(before)==1,'Qualified viewer copy changed: '+str(path))
    path.write_text(source.replace(before,after),encoding='utf-8')

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
        replace_one(project/'coverage/ui.ts',
                    "this.status.textContent='等待后端恢复；旧覆盖已清理'",
                    "this.status.textContent=''")
        replace_one(project/'coverage/ui.ts',
                    "'累计覆盖暂不可用；当前传感器覆盖仍可查看'",
                    "'覆盖数据暂不可用'")
        replace_one(project/'coverage/ui.ts',"+' 个；累计覆盖恢复中'", "+' 个'")
        replace_one(project/'missions/ui.ts',"'等待同连接快照恢复'","'暂无对象'")
        task_entry=project/'tasks/panel.ts'
        replace_one(task_entry,
                    '      this.catalog=catalog;this.items=rows.items;',
                    "      this.catalog=catalog;this.items=rows.items;this.root.classList.remove('is-unavailable');")
        replace_one(task_entry,
                    "    }catch(error){if(!this.busy&&epoch===this.epoch){this.catalog=null;this.items=[];this.status.textContent='任务服务不可用：'+String(error);}}",
                    """    }catch{
      let started=false;
      try{const response=await fetch('http://127.0.0.1:8001/api/control/v1/state',
        {cache:'no-store',signal:AbortSignal.timeout(2500)});
        if(response.ok)started=(await response.json() as {started?:boolean}).started===true;
      }catch{/* Keep the generic unavailable state when control is unreachable. */}
      if(!this.busy&&epoch===this.epoch){this.catalog=null;this.items=[];
        this.root.classList.add('is-unavailable');
        this.status.textContent=started?
          '仿真已开始，当前仿真段无法再创建或预览任务。请在左侧点击“重置”，等待新仿真段就绪后再保存并审查方案；确认下发会自动开始仿真。':
          '任务服务暂不可用，请检查连接后重试。';}
    }""")
        control_entry=project/'control/panel.ts'
        replace_one(control_entry,
                    "button.id='control-'+action;button.textContent=label;button.onclick=()=>void this.send(action);actions.append(button);",
                    """button.id='control-'+action;button.textContent=label;
      button.onclick=()=>{if(action==='start'&&!window.confirm(
        '直接开始仿真后，当前仿真段无法再创建或预览任务；可点击“重置”返回规划前状态。若要规划任务，请先在右侧保存草稿并审查方案；确认下发会自动开始仿真。仍要直接开始吗？'))return;
        void this.send(action);};actions.append(button);""")
        map_entry=project/'src/main.ts'
        replace_one(map_entry,
                    "    if(message)fail(message);viewer.scene.requestRender();",
                    "    if(message){notice.textContent=message;notice.hidden=false;}viewer.scene.requestRender();")
        replace_one(map_entry,
                    "local('在线影像不可用，已恢复本地矢量底图。'+String(error))",
                    "local('在线影像不可用，已恢复本地矢量底图。')")
        replace_one(map_entry,
                    "  let frames=0;",
                    "  baseSelect.value='satellite';baseSelect.dispatchEvent(new Event('change'));\n  let frames=0;")
        entry=project/'entities/main.ts';source_text=entry.read_text(encoding='utf-8')
        source_text="import { ExecutionPanel } from '../execution/panel';\n"+source_text
        anchor="  requireValue(viewer,'地图初始化未完成');"
        need(source_text.count(anchor)==1,'B03 map init changed')
        quality="""  const devicePixelRatio=Math.max(1,window.devicePixelRatio||1);
  const canvasPixelRatio=Math.min(2,Math.max(1.5,devicePixelRatio));
  viewer.useBrowserRecommendedResolution=false;
  viewer.resolutionScale=canvasPixelRatio/devicePixelRatio;
  viewer.scene.globe.maximumScreenSpaceError=2;
  viewer.resize();viewer.scene.requestRender();"""
        source_text=source_text.replace(anchor,anchor+'\n'+quality)
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
