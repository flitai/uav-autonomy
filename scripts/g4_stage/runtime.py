"""Final current-package two-entity runs and a reviewable twenty-entity GUI."""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid


ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
package=module('stage_package',Path(__file__).with_name('package.py'))
original=module('stage_original',ROOT/'scripts/g4_completion/runtime.py')
scale=module('stage_scale',ROOT/'scripts/g4_scale/runtime.py')
receipts=module('stage_confirmation',ROOT/'scripts/g3_acceptance/receipts.py')
load,save,sha,need=package.load,package.save,package.sha,package.need


class BundleHost:
    def start(self):
        self.owner.amase.check_port(8000)
        bundle=self.owner.args.bundle; manifest=package.verify(bundle,self.owner.root,self.owner.package_sha)
        directory=self.directory/('instance-'+str(len(self.instances)+1)); directory.mkdir()
        output=directory/'observer'
        argv=[str(self.python),'-I','-B','-X','utf8',str(bundle/'scripts/g4_stage/launch.py'),
            '--root',str(self.owner.root),'--manifest',str(self.manifest_path),'--manifest-sha256',sha(self.manifest_path),
            '--output',str(output),'--package-sha256',self.owner.package_sha]
        with (directory/'stdout.log').open('wb') as stdout,(directory/'stderr.log').open('wb') as stderr:
            process=subprocess.Popen(argv,cwd=directory,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        item={'pid':str(process.pid),'arguments':argv,'forced_termination':False}
        self.current=(directory,output,process,item); self.instances.append(self.current)
        self.wait(lambda:self.health(),'packaged HTTP listening',30)
        launch=load(directory/'package-launch.json')
        need(launch['packageSHA256']==self.owner.package_sha and Path(launch['bundle'])==bundle,'Loaded package differs')
        item['packageLaunchSHA256']=sha(directory/'package-launch.json')
        return self.current


class OriginalHost(BundleHost,original.recovery.hosts.GatewayHost): pass
class TwentyHost(BundleHost,scale.ScaleHost): pass


class StageInputs:
    def inputs(self):
        paths=[p for p in (self.root/'scripts/g4_stage').glob('*.py')]
        paths += [self.root/'config/g4-stage.json']
        paths += [self.root/('scripts/windows/'+name) for name in
                  ('run-g4-stage.ps1','run-g4-gateway.ps1','run-g4-session.ps1')]
        return super().inputs()+package.files(self.root,paths)

    def bind_package(self):
        self.package_sha=sha(self.args.bundle/'package.json')
        manifest=package.verify(self.args.bundle,self.root,self.package_sha)
        need({k:v.lower() for k,v in manifest['provenance']['artifacts'].items()}==
             {k:v.lower() for k,v in self.record['artifacts'].items()},'Candidate backend bytes differ')
        self.record.update(task='G4-T09',candidate=str(self.args.bundle.relative_to(self.root)),
            packageSHA256=self.package_sha,stageQualified=False,stabilityReference=package.predecessor(self.root))
        self.record['purpose']=self.args.purpose
        save(self.run/'result.json',self.record)

    def hold_demonstration(self):
        print('G4_SESSION_READY='+self.args.run_id+' URL=http://127.0.0.1:8000',flush=True)
        self.record['status']='demonstration-paused'; save(self.run/'result.json',self.record)
        remaining=self.operation_deadline-time.monotonic(); began=time.monotonic()
        while not (self.run/'request-stop').exists():
            self.operation_deadline=time.monotonic()+remaining; self.alive(); time.sleep(.2)
        self.manual_wait=getattr(self,'manual_wait',0)+time.monotonic()-began
        self.operation_deadline=time.monotonic()+remaining


class Original(StageInputs,original.Qualification):
    def prepare(self):
        self.record['g4Provenance']=original.recovery.environment.verify_handoff(self.root,self.context['baselineRunId'])
        self.web_python,_=original.recovery.environment.environment(self.root)
        original.recovery.complete.Completion.prepare(self)
        self.schema=original.load_schema(self.root)
        self.bind_package()

    def handshake(self):
        original.recovery.startup.Startup.handshake(self)
        ports={'amase':15555,'uxas':19999}
        for name,upstream in [('amase',self.ports['amasePort']),('uxas',self.ports['observerPort'])]:
            self.amase.check_port(ports[name])
            self.proxies[name]=original.recovery.proxies.ObserverProxy(ports[name],upstream)
            self.proxies[name].cut()
        self.host=OriginalHost(self,self.web_python,self.schema,ports); self.host.start()

class Twenty(StageInputs,scale.Scale):
    def prepare(self):
        super().prepare(); self.bind_package(); self.manual_wait=0; self.review_time=None

    def handshake(self):
        scale.startup.Startup.handshake(self)
        ports={'amase':15555,'uxas':19999}
        for name,upstream in [('amase',self.ports['amasePort']),('uxas',self.ports['observerPort'])]:
            self.amase.check_port(ports[name]); self.proxies[name]=scale.proxy.ObserverProxy(ports[name],upstream)
        self.host=TwentyHost(self,self.web_python,self.schema,ports); self.host.start()
        self.watch_directory=self.directory/'continuous-clients'
        with (self.directory/'watch.stdout').open('wb') as stdout,(self.directory/'watch.stderr').open('wb') as stderr:
            self.watcher=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',str(self.root/'tests/g4_scale/watch.py'),
                '--url',self.host.url,'--run-id',self.host.manifest['run_id'],'--output',str(self.watch_directory)],
                stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)

    def alive(self):
        super().alive()
        if getattr(self,'review_time',None) is not None:
            for row in self.monitor.rows:
                if row['type']=='afrl.cmasi.SessionStatus':
                    need(row['state']!=1 and row['timeMs']==self.review_time,'GUI resumed/reset after reviewed pause')
            self.monitor.rows.clear(); self.observer.rows.clear()
            health=self.host.health()
            need(health and health['ready'] and not health['error'],'Reviewed gateway is no longer live')

    def body(self,mode,fault,keep_gui):
        super().body(mode,fault,False)
        need(len(self.item['observedCompletions'])==20,'Final mixed tasks incomplete')
        self.wait('paused-session',lambda:any(r['type']=='afrl.cmasi.SessionStatus' and r['state']==2 for r in self.monitor.rows))
        sessions=[r for r in self.monitor.rows if r['type']=='afrl.cmasi.SessionStatus']
        self.review_time=sessions[-1]['timeMs']; self.monitor.rows.clear()
        save(self.directory/'preclose-case.json',self.item)
        with (self.directory/'review.stdout').open('wb') as stdout,(self.directory/'review.stderr').open('wb') as stderr:
            reviewer=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',str(self.root/'scripts/g4_stage/review.py'),
                '--root',str(self.root),'--directory',str(self.directory)],stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        # Review is automatic work; human waiting starts only after it passes.
        try:
            self.wait('independent-preclose-review',lambda:reviewer.poll() is not None,600)
        finally:
            if reviewer.poll() is None: reviewer.kill(); reviewer.wait(); need(False,'Review did not finish normally')
        need(reviewer.returncode==0,'Independent pre-close review failed')
        review=self.directory/'review/review.json'; need(load(review)['status']=='passed','Review incomplete')
        ready=dict(runId=self.args.run_id,phase='awaiting-confirmation',nonce=uuid.uuid4().hex,
            controllerPid=os.getpid(),javaPid=self.java_process.pid,uxasPid=self.cpp.pid,
            readyAtEpochSeconds=time.time(),reviewSHA256=sha(review),reviewPath=review.relative_to(self.run).as_posix(),
            pausedSimulationTimeMs=self.review_time,packageSHA256=self.package_sha)
        from sim_bridge.windows import process_identity
        ready['processes']=[process_identity(pid) for pid in (os.getpid(),self.java_process.pid,self.cpp.pid)]
        save(self.run/'gui-ready.json',ready); self.record['status']='awaiting-gui'; save(self.run/'result.json',self.record)
        print('G4_T09_GUI_READY='+self.args.run_id,flush=True)
        began=time.monotonic(); remaining=self.operation_deadline-began
        try:
            while True:
                self.operation_deadline=time.monotonic()+remaining; self.alive()
                request=self.run/'request-gui-acceptance.json'
                if request.exists():
                    confirmation=load(request)
                    receipts.validate_confirmation(ready,confirmation,sha(self.run/'gui-ready.json'),sha(review))
                    package.verify_files(review.parent,load(review)['files'])
                    self.record['manualGuiAcceptance']=self.item['manualGuiAcceptance']=confirmation
                    break
                time.sleep(.2)
        finally:
            self.manual_wait=time.monotonic()-began; self.operation_deadline=time.monotonic()+remaining
        self.record['status']='running'; self.record['manualWaitSeconds']=self.manual_wait
        save(self.run/'result.json',self.record)

    def audit(self):
        scale.mixed.Capture.audit(self)
        need(len(self.item['observedCompletions'])==20 and len(self.host.records)==3,'Final mixed evidence incomplete')
        need(self.item.get('manualGuiAcceptance'),'Current GUI confirmation missing')

    def execute(self):
        self.prepare(); mode=self.args.mode
        self.config['modes'][mode]=deepcopy(self.config['modes'][mode])
        offset=10000 if mode=='Headless' else 0
        self.config['modes'][mode]['entityPorts']={entity:9000+int(entity)+offset for entity in scale.IDS}
        self.started=time.monotonic(); self.operation_deadline=self.started+2650
        case=self.case('中文 空格 '+mode,mode)
        need(case['status']=='passed',case.get('error','Final GUI failed'))
        need(time.monotonic()-self.started-self.manual_wait<2700,'Automatic wall budget exceeded')
        need(self.inputs()==self.record['inputs'],'Stage input changed')
        package.verify(self.args.bundle,self.root,self.package_sha)
        self.record.update(status='passed',inputsUnchanged=True,automaticWallSeconds=time.monotonic()-self.started-self.manual_wait)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True); parser.add_argument('--java-home',type=Path,required=True)
    parser.add_argument('--baseline-run-id',required=True); parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--scene',choices=['Original','Mixed20'],required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--purpose',choices=['Qualification'],default='Qualification')
    parser.add_argument('--mode',choices=['Headless','Gui'],default='Gui')
    args=parser.parse_args(); args.root=args.root.resolve(); args.bundle=args.bundle.resolve()
    need(args.run_id.startswith('g4-t09-') and '/' not in args.run_id and '\\' not in args.run_id,'Invalid run identity')
    need(args.purpose!='Qualification' or args.scene=='Original' or args.mode=='Gui','Final mixed GUI required')
    args.keep_gui=False; args.verify=args.purpose=='Qualification'; args.seconds=785
    directory=args.root/'out/runs'/args.run_id; directory.mkdir()
    context={'baselineRunId':args.baseline_run_id,'javaHome':str(args.java_home.resolve())}
    for key,value in [('configuration','startup'),('executionConfiguration','execution'),('completionConfiguration','completion')]:
        context[key]=str(args.root/('config/g3-'+value+'.json'))
    save(directory/'context.json',context)
    task=(Original if args.scene=='Original' else Twenty)(args)
    try: task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed',error=str(error),traceback=traceback.format_exc()); print(task.record['traceback'],flush=True); return 1
    finally:
        save(directory/'result.json',task.record)
        print('G4_T09_RUN_ID='+args.run_id+' STATUS='+task.record['status'],flush=True)


if __name__=='__main__': sys.exit(main())
