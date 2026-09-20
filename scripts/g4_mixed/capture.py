"""Candidate real mixed flights with raw navigation, analysis and gateway records.

Post-run independent execution/statistics audits are required for qualification.
"""
import argparse
import hashlib
from datetime import datetime
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
sys.path.insert(0,str(ROOT/'src'))


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value); return value


planning=module('mixed_flight_planning',Path(__file__).with_name('planning.py'))
hosts=module('mixed_flight_host',Path(__file__).with_name('host.py'))
environment=module('mixed_flight_environment',ROOT/'scripts/g4_environment/manage.py')
from sim_bridge.codec import load_schema
from sim_bridge.journal import Journal
from sim_bridge.state import State
load,save,require,sha=planning.load,planning.save,planning.require,planning.sha


class Capture(planning.Planning):
    def inputs(self):
        files=[p for d in ('src/sim_bridge','apps/gis_gateway') for p in (self.root/d).rglob('*') if p.is_file()]
        files += [self.root/p for p in ('scripts/g4_recovery/host.py','scripts/g4_environment/manage.py',
            'scripts/g3_execution/ExecutionProbe.java','scripts/g3_completion/CompletionProbe.java')]
        return super().inputs()+[{'path':p.relative_to(self.root).as_posix(),'sha256':sha(p)} for p in sorted(files)]

    def prepare(self):
        super().prepare(); self.record['scope']='candidate-flight-recording'
        self.web_python,_=environment.environment(self.root); self.schema=load_schema(self.root)
        classes=self.root/'out/build/g4-mixed'/self.args.run_id/'flight-classes'; classes.mkdir()
        sources=[self.root/'scripts/g3_execution/ExecutionProbe.java',self.root/'scripts/g3_completion/CompletionProbe.java']
        process=subprocess.run([str(Path(self.context['javaHome'])/'bin/javac.exe'),'-encoding','UTF-8','--release','11','-cp',
            os.pathsep.join(map(str,self.cp)),'-d',str(classes),*map(str,sources)],capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        (self.run/'flight-javac.stdout').write_bytes(process.stdout); (self.run/'flight-javac.stderr').write_bytes(process.stderr)
        require(process.returncode==0,'Flight probes failed compilation'); self.cp.append(classes)

    def files(self,mode,fault):
        self.host,self.watcher=None,None
        super().files(mode,fault)
        entities=ET.parse(self.java_dir/'config/EntityControl.xml')
        ET.SubElement(entities.find('DefaultAircraft'),'Module',Class='validation.g3.ExecutionProbe')
        entities.write(self.java_dir/'config/EntityControl.xml',encoding='utf-8',xml_declaration=True)
        plugins=ET.parse(self.java_dir/'config/Plugins.xml')
        ET.SubElement(plugins.getroot(),'Plugin',Class='validation.g3.CompletionProbe')
        plugins.write(self.java_dir/'config/Plugins.xml',encoding='utf-8',xml_declaration=True)

    def handshake(self):
        super().handshake()
        self.host=hosts.GatewayHost(self,self.web_python,self.schema,{'amase':self.ports['amasePort'],'uxas':self.ports['observerPort']})
        self.host.start()

    def witness(self,name):
        snapshot=self.host.live(); output=self.host.current[1]; manifest=self.host.manifest
        journal=Journal(output/'journal-binding.json',manifest['run_id'],self.schema,manifest['entity_ids'])
        expected=State(manifest['run_id'],manifest['entity_ids'])
        for event in journal.read(journal.boundary()):
            expected.apply(event)
            if expected.sequence==int(snapshot['sequence']): break
        require(expected.snapshot()==snapshot['state'],'Gateway state differs from its exact committed boundary')
        save(self.directory/(name+'.json'),snapshot); return snapshot

    def body(self,mode,fault,keep_gui):
        super().body(mode,fault,keep_gui)
        self.witness('planned-scene')
        self.watch_directory=self.directory/'continuous-clients'
        with (self.directory/'watch.stdout').open('wb') as stdout,(self.directory/'watch.stderr').open('wb') as stderr:
            self.watcher=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',str(self.root/'tests/g4_mixed/watch.py'),
                '--url',self.host.url,'--run-id',self.host.manifest['run_id'],'--output',str(self.watch_directory)],
                stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('three-clients',lambda:self.host.health()['metrics']['clients']==3)
        for number in (1,2):
            began=time.monotonic(); self.wait('before-restart-'+str(number),lambda:time.monotonic()-began>=3)
            self.host.stop(); self.host.start(); self.witness('restart-'+str(number))
            self.wait('three-clients-restored-'+str(number),lambda:self.host.health()['metrics']['clients']==3)
        expected={row['taskId']:row['entityId'] for row in self.scene['assignments']}
        completions={}; cursor=0; latest=0; next_print=0
        def finished():
            nonlocal cursor,latest,next_print
            for row in self.observer.rows[cursor:]:
                cursor+=1
                if row['type']=='afrl.cmasi.SessionStatus':
                    require(row['realTimeMultiple']==1,'Unexpected simulation rate'); latest=max(latest,int(row['timeMs']))
                if row['type']=='uxas.messages.task.TaskComplete':
                    node=planning.ET.fromstring(planning.base64.b64decode(row['xmlBase64']))
                    task=node.findtext('TaskID'); ids=[n.text for n in node.findall('EntitiesInvolved/int64')]
                    require(task in expected and ids==[expected[task]] and task not in completions,'Wrong or duplicate completion')
                    require(row['sourceEntity']=='100','Non-UxAS completion')
                    completions[task]={'entityId':ids[0],'timeMs':node.findtext('TimeTaskCompleted'),'message':row}
                if row['type']=='afrl.cmasi.AirVehicleState': latest=max(latest,int(row['timeMs']))
            health=self.host.health(); require(health and health['ready'] and not health.get('error'),'Gateway failed during real flight')
            require(self.watcher.poll() is None,'Browser consumer failed during real flight')
            if time.monotonic()>=next_print:
                print('G4 mixed '+self.item['name']+': sim='+str(latest)+' completed='+str(len(completions))+'/'+str(len(expected)),flush=True)
                next_print=time.monotonic()+30
            require(latest<1795000,'Task did not complete within fixed scene')
            return len(completions)==len(expected) and latest>=max(int(x['timeMs']) for x in completions.values())+3000
        self.wait('all-task-completions',finished,1900)
        self.item['observedCompletions']=completions
        (self.java_dir/'request-pause').touch()
        self.wait('flight-paused',lambda:any(e['kind']=='paused' for e in self.amase.events(self.java_dir)))
        (self.java_dir/'request-analysis').touch()
        self.wait('analysis-exported',lambda:(self.java_dir/'analysis-done').exists())
        snapshot=self.witness('completed-scene')
        require(set(snapshot['state']['entities'])==set(self.ids),'Gateway entity set differs')
        for task,entity in expected.items():
            state=snapshot['state']['tasks'][task]
            require(state['backend_completed'] and state['completed_entity_ids']==[entity]
                    and state['completed_time_ms']==completions[task]['timeMs'],'Gateway completion differs')
        target={'run_id':snapshot['run_id'],'sequence':snapshot['sequence'],
                'state_sha256':hashlib.sha256(json.dumps(snapshot['state'],sort_keys=True).encode()).hexdigest()}
        pending=self.watch_directory/'expected-final.tmp'; save(pending,target)
        pending.replace(self.watch_directory/'expected-final.json')
        def clients_caught_up():
            for index in range(3):
                path=self.watch_directory/('final-'+str(index)+'.json')
                if not path.is_file(): return False
                require(load(path)==target,'Client acknowledged a different final state')
            return True
        self.wait('paused-client-catch-up',clients_caught_up,90)
        self.item['clientFinalBoundary']=target

    def cleanup(self):
        try:
            if self.watcher:
                (self.watch_directory/'request-stop').touch()
                try: self.watcher.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.watcher.kill(); self.watcher.wait(timeout=10); self.item.setdefault('cleanupErrors',[]).append('Client forced termination')
                self.item['continuousClientProcess']={'pid':str(self.watcher.pid),'exitCode':self.watcher.returncode}
                if self.watcher.returncode: self.item.setdefault('cleanupErrors',[]).append('Continuous clients failed')
            if self.host and self.host.current: self.host.stop()
        finally:
            super().cleanup(); self.amase.check_port(8000)
        if self.host: self.item['gatewayInstances']=self.host.records

    def audit(self):
        super().audit()
        require(self.item.get('observedCompletions') and (self.java_dir/'analysis-events.tsv').is_file(),'Incomplete flight capture')
        require(load(self.watch_directory/'result.json')['status']=='passed','Client evidence failed')
        require(all(r['status']=='passed' for r in self.host.records),'Gateway instance failed')
        self.item.update(realCompletionCaptured=True,independentExecutionAndStatisticsAuditRequired=True)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--java-home',type=Path,required=True); parser.add_argument('--amase-build',required=True)
    parser.add_argument('--automatic-run',required=True)
    args=parser.parse_args(); args.root=args.root.resolve(); args.run_id='g4-t07-capture-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    args.keep_gui=False; args.mode='Headless'; args.verify=True
    directory=args.root/'out/runs'/args.run_id; directory.mkdir()
    save(directory/'context.json',{'baselineRunId':'g3-t01-check-20260919-233710-372','javaHome':str(args.java_home.resolve())})
    task=Capture(args)
    try: task.execute(); return 0
    except Exception as error: task.record.update(status='failed',error=str(error),traceback=traceback.format_exc()); return 1
    finally:
        save(directory/'result.json',task.record)
        print('G4_T07_CAPTURE_RUN_ID='+args.run_id+' STATUS='+task.record['status'],flush=True)


if __name__=='__main__': sys.exit(main())
