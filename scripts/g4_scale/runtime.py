"""Fixed twenty real entities, independent observer recovery and thirty-minute runs."""
import argparse
import base64
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
import xml.etree.ElementTree as ET


ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
mixed=module('scale_mixed',ROOT/'scripts/g4_mixed/capture.py')
metrics=module('scale_metrics',Path(__file__).with_name('metrics.py'))
proxy=module('scale_proxy',ROOT/'tests/g4_recovery/proxy.py')
startup=mixed.planning.startup
load,save,sha,need=mixed.load,mixed.save,mixed.sha,mixed.require
IDS=['400','500']+[str(i) for i in range(600,618)]
KINDS=['line']*8+['point']*6+['area']*6


class ScaleHost(mixed.hosts.GatewayHost):
    def live(self):
        def ready():
            value=self.health()
            need(value and value['error'] is None,'Gateway degraded: '+str(value))
            return value if value['ready'] else None
        value=self.wait(ready,'complete twenty-entity live snapshot',120)
        status,snapshot=self.request('/api/v1/snapshot')
        need(status==200 and snapshot['stream_id']==value['stream_id'],'Snapshot changed at ready check')
        return snapshot


class Scale(mixed.Capture):
    def inputs(self):
        paths=[p for folder in ('scripts/g4_scale','tests/g4_scale') for p in (self.root/folder).rglob('*') if p.is_file()]
        paths += [self.root/'tests/g4_recovery/proxy.py',self.root/'config/g4-baseline.json',
                  self.root/'scripts/windows/run-g4-scale.ps1']
        return super().inputs()+[{'path':p.relative_to(self.root).as_posix(),'sha256':sha(p)} for p in sorted(paths)]

    def prepare(self):
        startup.Startup.prepare(self)
        self.record.update(task='G4-T08',scope='twenty-entity-stability',stageQualified=False,
                           diagnostic=self.args.seconds!=1800,machine=metrics.machine())
        self.record['g4Provenance']=mixed.environment.verify_handoff(self.root,self.context['baselineRunId'])
        qualified=load(self.root/'out/runs/g4-t07-qualified-20260920-081353-913195/result.json')
        need(qualified['status']=='passed' and qualified['stageQualified'],'T07 formal qualification missing')
        mixed.environment.verify_files(self.root,qualified['receipts'])
        revision=self.record['g4Provenance']['uxasScaleRevision']
        need(revision and revision['parentFormalUxas']==qualified['provenance']['amaseRevision']['formalUxas'] and
             all(self.record['g4Provenance']['artifacts'][key]==qualified['provenance']['artifacts'][key]
                 for key in ('amaseSHA256','lmcpSHA256')),'Scale combination does not descend from T07')
        self.web_python,_=mixed.environment.environment(self.root);self.schema=mixed.load_schema(self.root)
        self.ids,self.kinds=IDS,KINDS
        self.record['taskAssignments']=[{'entityId':entity,'taskId':str(3000+i),'kind':KINDS[i]} for i,entity in enumerate(IDS)]
        classes=self.root/'out/build/g4-scale'/self.args.run_id/'classes';classes.mkdir(parents=True)
        sources=[self.root/'scripts/g3_execution/ExecutionProbe.java',self.root/'scripts/g3_completion/CompletionProbe.java']
        result=subprocess.run([str(Path(self.context['javaHome'])/'bin/javac.exe'),'-encoding','UTF-8','--release','11','-cp',
            os.pathsep.join(map(str,self.cp)),'-d',str(classes),*map(str,sources)],capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        (self.run/'flight-javac.stdout').write_bytes(result.stdout);(self.run/'flight-javac.stderr').write_bytes(result.stderr)
        need(result.returncode==0,'Scale probes failed compilation');self.cp.append(classes)
        self.proxies={};self.event_offset=0;self.event_tail=b'';self.event_kinds=set();self.host=None;self.watcher=None

    def files(self,mode,fault):
        self.mode=mode;self.proxies={};self.event_offset=0;self.event_tail=b'';self.event_kinds=set()
        super().files(mode,fault)
        self.sampler=metrics.Sampler(self.directory/'resources.jsonl')
        self.item.update(durationSeconds=self.args.seconds,sceneDurationSeconds=1800,actualRate=1)

    def launch(self,directory,argv):
        if directory==self.java_dir:
            argv=[('-Djava.awt.headless='+str(self.mode=='Headless').lower()) if str(a).startswith('-Djava.awt.headless=') else a for a in argv]
            argv.insert(1,'-Xmx2g')
        return super().launch(directory,argv)

    def alive(self):
        need(time.monotonic()<self.operation_deadline,'timeout:whole-run')
        for _,child,row in self.children:need(child.poll() is None,'process-exited:'+str(row['pid']))
        for stream in self.streams:need(stream.error is None and not stream.disconnected,'stream-failed:'+stream.name+':'+str(stream.error))
        for value in self.proxies.values():need(value.error is None,'Fault proxy failed: '+str(value.error))
        path=self.java_dir/'events.jsonl' if self.java_dir else None
        if path and path.exists():
            with path.open('rb') as stream:
                stream.seek(self.event_offset)
                while block:=stream.read(65536):
                    self.event_offset+=len(block);data=self.event_tail+block;lines=data.split(b'\n');self.event_tail=lines.pop()
                    for line in lines:
                        event=json.loads(line);self.event_kinds.add(event['kind'])
            need('unexpected-start' not in self.event_kinds,'AMASE started before barrier')
        # Host recovery waits call alive too, so resource sampling continues
        # throughout lengthy rebuilds instead of omitting their peaks.
        if (self.host and self.host.current and self.host.current[2].poll() is None and
                self.watcher and self.watcher.poll() is None and time.monotonic()>=self.sampler.next):
            health=self.host.health()
            if health:
                self.sampler.sample({'amase':self.java_process.pid,'uxas':self.cpp.pid,'gateway':self.host.current[2].pid,
                    'clients':self.watcher.pid,'controller':os.getpid()},health,health['source_time_ms'])

    def handshake(self):
        startup.Startup.handshake(self)
        ports={'amase':15555,'uxas':19999}
        for name,upstream in [('amase',self.ports['amasePort']),('uxas',self.ports['observerPort'])]:
            self.amase.check_port(ports[name]);self.proxies[name]=proxy.ObserverProxy(ports[name],upstream)
        self.host=ScaleHost(self,self.web_python,self.schema,ports);self.host.start()
        # Start all consumers before the simulation barrier; while initial
        # data is incomplete they receive health and retry for a new snapshot.
        self.watch_directory=self.directory/'continuous-clients'
        with (self.directory/'watch.stdout').open('wb') as stdout,(self.directory/'watch.stderr').open('wb') as stderr:
            self.watcher=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',str(self.root/'tests/g4_scale/watch.py'),
                '--url',self.host.url,'--run-id',self.host.manifest['run_id'],'--output',str(self.watch_directory)],
                stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)

    def body(self,mode,fault,keep_gui):
        mixed.planning.Planning.body(self,mode,fault,False)
        self.witness('planned-scene')
        self.wait('three-clients',lambda:self.host.health()['metrics']['clients']==3)
        expected={r['taskId']:r['entityId'] for r in self.scene['assignments']}
        completions={};latest=0;next_print=0;actions=[];active_fault=False
        if self.args.seconds==1800:
            schedule=[(60,'restart'),(120,'amase-half-cut'),(140,'restore'),(240,'uxas-cut'),(260,'restore'),
                      (700,'both-cut'),(780,'restore'),(900,'restart')]
        else:schedule=[(20,'restart'),(40,'restart')]
        while True:
            self.alive()
            batch=self.observer.rows[:];del self.observer.rows[:len(batch)]
            del self.monitor.rows[:len(self.monitor.rows)]
            for row in batch:
                if row['type']=='afrl.cmasi.SessionStatus':
                    need(row['realTimeMultiple']==1,'Unexpected simulation rate');latest=max(latest,int(row['timeMs']))
                if row['type']=='afrl.cmasi.AirVehicleState':latest=max(latest,int(row['timeMs']))
                if row['type']=='uxas.messages.task.TaskComplete':
                    node=ET.fromstring(base64.b64decode(row['xmlBase64']));task=node.findtext('TaskID')
                    entities=[n.text for n in node.findall('EntitiesInvolved/int64')]
                    need(task in expected and entities==[expected[task]] and task not in completions and row['sourceEntity']=='100',
                         'Wrong or repeated completion')
                    completions[task]={'entityId':entities[0],'timeMs':node.findtext('TimeTaskCompleted'),'message':row}
            if schedule and latest>=schedule[0][0]*1000:
                at,action=schedule.pop(0);before=self.host.health()
                if action=='restart':
                    self.host.stop();self.host.start();snapshot=self.host.live()
                    save(self.directory/('restart-'+str(at)+'.json'),snapshot)
                elif action=='restore':
                    for value in self.proxies.values():value.restore()
                    snapshot=self.host.live();save(self.directory/('restore-'+str(at)+'.json'),snapshot);active_fault=False
                else:
                    active_fault=True
                    channels=['amase','uxas'] if action=='both-cut' else [action.split('-')[0]]
                    for channel in channels:self.proxies[channel].cut(partial=action=='amase-half-cut')
                    self.host.wait(lambda:not self.host.health()['ready'],'observation suspension')
                    need(self.host.request('/api/v1/snapshot')[0]==503,'Incomplete state published during recovery')
                after=self.host.health();actions.append({'atSimulationMs':str(latest),'action':action,'before':before,'after':after})
                self.item['recoveryActions']=actions;self.transition(action,simulationMs=str(latest))
            health=self.host.health()
            need(health and health['error'] is None,'Gateway failed: '+str(health))
            if not active_fault:need(health['ready'],'Gateway unexpectedly not ready')
            need(self.watcher.poll() is None,'Client process exited early')
            self.sampler.sample({'amase':self.java_process.pid,'uxas':self.cpp.pid,'gateway':self.host.current[2].pid,
                                 'clients':self.watcher.pid,'controller':os.getpid()},health,latest)
            if time.monotonic()>=next_print:
                print('G4 scale '+mode+': sim='+str(latest)+' tasks='+str(len(completions))+'/20 recovery='+health['status'],flush=True)
                next_print=time.monotonic()+30
            if latest>=self.args.seconds*1000:break
            time.sleep(.1)
        need(not schedule,'Stability recovery schedule incomplete')
        if self.args.seconds==1800:need(len(completions)==20,'Not every assigned task completed')
        self.item['observedCompletions']=completions;self.item['lastSimulationMs']=str(latest)
        (self.java_dir/'request-pause').touch();self.wait('flight-paused',lambda:'paused' in self.event_kinds)
        (self.java_dir/'request-analysis').touch();self.wait('analysis-exported',lambda:(self.java_dir/'analysis-done').exists(),90)
        snapshot=self.witness('completed-scene')
        need(set(snapshot['state']['entities'])==set(IDS) and len(snapshot['state']['tasks'])==20,'Final objects differ')
        for task,value in completions.items():
            state=snapshot['state']['tasks'][task]
            need(state['backend_completed'] and state['completed_entity_ids']==[value['entityId']] and
                 state['completed_time_ms']==value['timeMs'],'Browser completion differs')
        target={'run_id':snapshot['run_id'],'sequence':snapshot['sequence'],
                'state_sha256':hashlib.sha256(json.dumps(snapshot['state'],sort_keys=True).encode()).hexdigest()}
        pending=self.watch_directory/'expected-final.tmp';save(pending,target);pending.replace(self.watch_directory/'expected-final.json')
        def clients_ready():
            return all((self.watch_directory/('final-'+str(i)+'.json')).exists() and
                       load(self.watch_directory/('final-'+str(i)+'.json'))==target for i in range(3))
        self.wait('paused-client-catch-up',clients_ready,90);self.item['clientFinalBoundary']=target

    def cleanup(self):
        try:super().cleanup()
        finally:
            for value in self.proxies.values():value.close()
            self.item['observerProxies']={name:value.summary() for name,value in self.proxies.items()}
            for port in (15555,19999):self.amase.check_port(port)

    def audit(self):
        if self.args.seconds==1800:super().audit()
        else:
            mixed.planning.Planning.audit(self)
            need(load(self.watch_directory/'result.json')['status']=='passed','Diagnostic clients failed')
        need(len(self.item['plans'])==20 and len(self.host.records)==3,'Planning or gateway instances missing')
        self.item.update(resourceSamples=self.sampler.count,independentExecutionAndStatisticsAuditRequired=True)

    def execute(self):
        self.prepare()
        for mode in self.args.modes:
            self.host=None;self.watcher=None;self.proxies={}
            self.config['modes'][mode]=deepcopy(self.config['modes'][mode])
            offset=10000 if mode=='Headless' else 0
            self.config['modes'][mode]['entityPorts']={entity:9000+int(entity)+offset for entity in IDS}
            self.started=time.monotonic();self.operation_deadline=self.started+2650
            name='中文 空格 '+mode
            case=self.case(name,mode)
            need(time.monotonic()-self.started<=2700,'Mode exceeded automatic wall budget')
            need(case['status']=='passed',case.get('error','Scale run failed'))
        need(self.inputs()==self.record['inputs'],'Scale sources changed during run')
        self.amase.verify_records(self.root,self.baseline['frozenInputs'])
        startup.release.resolve(self.root,self.baseline['provenance'])
        self.amase.candidate(self.root,None)
        self.record.update(status='passed',inputsUnchanged=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--java-home',type=Path,required=True);parser.add_argument('--baseline-run-id',required=True)
    parser.add_argument('--modes',nargs='+',choices=['Headless','Gui'],default=['Headless','Gui'])
    parser.add_argument('--seconds',type=int,choices=[60,1800],default=1800)
    args=parser.parse_args();args.root=args.root.resolve();args.keep_gui=False;args.verify=False;args.mode=args.modes[0]
    args.run_id='g4-t08-'+('diagnostic-' if args.seconds!=1800 else 'capture-')+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    directory=args.root/'out/runs'/args.run_id;directory.mkdir()
    save(directory/'context.json',{'baselineRunId':args.baseline_run_id,'javaHome':str(args.java_home.resolve()),
                                'configuration':str(args.root/'config/g3-startup.json')})
    task=Scale(args)
    try:task.execute();return 0
    except Exception as error:task.record.update(status='failed',error=str(error),traceback=traceback.format_exc());return 1
    finally:
        save(directory/'result.json',task.record)
        print('G4_T08_RUN_ID='+args.run_id+' STATUS='+task.record['status'],flush=True)
        if task.record['status']=='failed':print(task.record['traceback'],flush=True)


if __name__=='__main__':sys.exit(main())
