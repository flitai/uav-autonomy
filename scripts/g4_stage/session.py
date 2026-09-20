"""Ordinary G5 backend/observer session, without acceptance fault injection."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback


spec=importlib.util.spec_from_file_location('session_stage',Path(__file__).with_name('runtime.py'))
stage=importlib.util.module_from_spec(spec); spec.loader.exec_module(stage)
save,load,need=stage.save,stage.load,stage.need


class Session:
    def body(self,mode,fault,keep_gui):
        if self.args.scene=='Original':
            stage.original.recovery.startup.Startup.body(self,mode,'',False)
            expected={'1000':'400'}
        else:
            stage.scale.mixed.planning.Planning.body(self,mode,'',False)
            expected={row['taskId']:row['entityId'] for row in self.scene['assignments']}
        for proxy in self.proxies.values(): proxy.restore()
        self.host.live(); self.item['sessionReady']=True
        self.record['status']='demonstration-running'; save(self.run/'result.json',self.record)
        print('G4_SESSION_READY='+self.args.run_id+' URL=http://127.0.0.1:8000',flush=True)
        latest=0; completions={}; cursor=0
        while not (self.run/'request-stop').exists():
            self.alive()
            for row in self.observer.rows[cursor:]:
                cursor+=1
                if row['type'] in ('afrl.cmasi.SessionStatus','afrl.cmasi.AirVehicleState'): latest=max(latest,int(row['timeMs']))
                if row['type']=='uxas.messages.task.TaskComplete':
                    node=stage.original.recovery.complete.completion.xml(row); task=node.findtext('TaskID')
                    need(task in expected and [n.text for n in node.findall('EntitiesInvolved/int64')]==[expected[task]],'Unexpected completion identity')
                    need(task not in completions,'Repeated completion'); completions[task]=node.findtext('TimeTaskCompleted')
            if self.args.scene=='Mixed20':
                self.observer.rows.clear(); self.monitor.rows.clear(); cursor=0
            health=self.host.health(); need(health and health['error'] is None,'Gateway failed')
            completed=len(completions)==len(expected)
            if (self.args.scene=='Original' and completed and latest>=int(completions['1000'])+3000) or latest>=785000:
                need(completed,'Not all assigned tasks completed within the scene')
                (self.java_dir/'request-pause').touch()
                self.wait('session-paused',lambda:any(row['type']=='afrl.cmasi.SessionStatus' and row['state']==2 for row in self.monitor.rows))
                (self.java_dir/'request-analysis').touch(); self.wait('session-analysis',lambda:(self.java_dir/'analysis-done').exists(),90)
                snapshot=self.host.live(); save(self.directory/'completed-scene.json',snapshot)
                for task,entity in expected.items():
                    observed=snapshot['state']['tasks'][task]
                    need(observed['backend_completed'] and observed['completed_entity_ids']==[entity] and
                         observed['completed_time_ms']==completions[task],'Session completion differs from gateway')
                self.hold_demonstration(); break
            time.sleep(.1)
        self.item['observedCompletions']=completions

    def audit(self):
        need(self.item.get('sessionReady') and self.host.records and all(row['status']=='passed' for row in self.host.records),
             'Session did not initialize and close normally')
        self.item['demonstrationOnly']=True

    def execute(self):
        self.prepare(); mode=self.args.mode
        if self.args.scene=='Mixed20':
            self.config['modes'][mode]=deepcopy(self.config['modes'][mode]); offset=10000 if mode=='Headless' else 0
            self.config['modes'][mode]['entityPorts']={entity:9000+int(entity)+offset for entity in stage.scale.IDS}
        self.started=time.monotonic(); self.operation_deadline=self.started+2650
        case=self.case('session-'+mode.lower(),mode)
        need(case['status']=='passed',case.get('error','Session failed'))
        need(self.inputs()==self.record['inputs'],'Session sources changed')
        stage.package.verify(self.args.bundle,self.root,self.package_sha)
        self.record.update(status='passed',inputsUnchanged=True,demonstrationOnly=True,stageQualified=False)


class Original(Session,stage.Original): pass


class Twenty(Session,stage.Twenty):
    def handshake(self):
        stage.scale.startup.Startup.handshake(self)
        # Ordinary session observes the real endpoints directly; no fault relays or test clients.
        self.host=stage.TwentyHost(self,self.web_python,self.schema,
            {'amase':self.ports['amasePort'],'uxas':self.ports['observerPort']})
        self.host.start()


def main():
    parser=argparse.ArgumentParser()
    for name in ('root','java-home','bundle'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--baseline-run-id',required=True); parser.add_argument('--run-id',required=True)
    parser.add_argument('--scene',choices=['Original','Mixed20'],default='Mixed20'); parser.add_argument('--mode',choices=['Headless','Gui'],default='Gui')
    args=parser.parse_args(); args.root=args.root.resolve(); args.bundle=args.bundle.resolve()
    need(args.run_id.startswith('g4-t09-demo-') and '/' not in args.run_id and '\\' not in args.run_id,'Invalid session identity')
    args.purpose='Demonstration'; args.keep_gui=False; args.verify=False; args.seconds=785
    directory=args.root/'out/runs'/args.run_id; directory.mkdir()
    context={'baselineRunId':args.baseline_run_id,'javaHome':str(args.java_home.resolve())}
    for key,name in [('configuration','startup'),('executionConfiguration','execution'),('completionConfiguration','completion')]:
        context[key]=str(args.root/('config/g3-'+name+'.json'))
    save(directory/'context.json',context); task=(Original if args.scene=='Original' else Twenty)(args)
    try: task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed',error=str(error),traceback=traceback.format_exc()); print(task.record['traceback'],flush=True); return 1
    finally: save(directory/'result.json',task.record)


if __name__=='__main__': sys.exit(main())
