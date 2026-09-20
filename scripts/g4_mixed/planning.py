"""Candidate-only mixed-task planning diagnostic; never publishes or accepts G4."""
import argparse
import base64
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from xml.dom import minidom
import xml.etree.ElementTree as ET


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value); return value


ROOT=Path(__file__).resolve().parents[2]
startup=module('mixed_startup',ROOT/'scripts/g3_integration/runtime.py')
scenes=module('mixed_scenes',Path(__file__).with_name('scene.py'))
gates=module('mixed_gates',Path(__file__).with_name('gates.py'))
save,load,sha,require=startup.save,startup.load,startup.sha,startup.require


class Planning(startup.Startup):
    def inputs(self):
        paths=[p for d in ('scripts/g4_mixed','tests/g4_mixed') for p in (self.root/d).rglob('*') if p.is_file()]
        return super().inputs()+[{'path':p.relative_to(self.root).as_posix(),'sha256':sha(p)} for p in sorted(paths)]

    def prepare(self):
        self.record.update(task='G4-T07',scope='candidate-planning-diagnostic',stageQualified=False)
        self.config=load(self.root/'config/g3-startup.json')
        parent=self.root/'out/runs'/self.context['baselineRunId']; self.baseline=load(parent/'baseline.json')
        require(load(parent/'result.json')['status']==load(parent/'entry-result.json')['status']=='passed','Invalid historical baseline')
        self.uxas,pointer=startup.release.resolve(self.root,self.baseline['provenance'])
        self.folder,info,self.lmcp_jar=self.amase.candidate(self.root,self.args.amase_build)
        automatic=load(self.root/'out/runs'/self.args.automatic_run/'result.json')
        require(automatic['status']=='automatic-passed' and automatic['buildRunId']==info['runId']
                and len(automatic['cases'])==11 and all(c['status']=='passed' for c in automatic['cases']), 'Unqualified candidate automatic evidence')
        self.record.update(inputs=self.inputs(),formalUxas=pointer,amaseBuildRunId=info['runId'],candidateAutomaticRunId=self.args.automatic_run,
            artifacts={'amaseSHA256':sha(self.folder/'OpenAMASE.jar'),'lmcpSHA256':sha(self.lmcp_jar),'uxasSHA256':sha(self.uxas/'uxas.exe')})
        # The historical G3 source list remains immutable. All unchanged files
        # must match, and the candidate statistics/TCP changes bind to the
        # candidate's already checked build inputs, never to fabricated hashes.
        changes=[]; allowed={f'OpenAMASE/OpenAMASE/src/Amase/avtas/amase/analysis/{n}.java'
                            for n in ('PointSearchHighlight','AreaSearchHighlight','SearchTaskAnalysis')}
        allowed.add('OpenAMASE/OpenAMASE/src/Amase/avtas/amase/network/TcpServer.java')
        for row in self.baseline['frozenInputs']:
            current=sha(self.root/row['path'])
            if current!=row['sha256']:
                require(row['path'] in allowed,'Unexpected change outside candidate statistics: '+row['path'])
                changes.append({'path':row['path'],'previousSHA256':row['sha256'],'candidateSHA256':current})
        self.record['candidateSourceChanges']=changes
        sys.path.insert(0,str(self.root/'out/generated/lmcp/py'))
        from lmcp import LMCPFactory
        self.factory=LMCPFactory
        classes=self.root/'out/build/g4-mixed'/self.args.run_id/'classes'; classes.mkdir(parents=True)
        self.cp=[self.folder/'OpenAMASE.jar',self.lmcp_jar]+[self.root/self.amase.PROJECT/p for p in self.amase.LIBRARIES]
        self.java=Path(self.context['javaHome'])/'bin/java.exe'
        result=subprocess.run([str(Path(self.context['javaHome'])/'bin/javac.exe'),'-encoding','UTF-8','--release','11','-cp',
            os.pathsep.join(map(str,self.cp)),'-d',str(classes),str(self.root/'scripts/g3_integration/StartupProbe.java')],
            capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        (self.run/'javac.stdout').write_bytes(result.stdout); (self.run/'javac.stderr').write_bytes(result.stderr)
        require(result.returncode==0,'Diagnostic probe compilation failed'); self.cp.append(classes)

    def files(self,mode,fault):
        super().files(mode,'')
        self.scene=scenes.build(self.root,self.directory/'scene',self.kinds,self.ids)
        self.gate=gates.Gate(self.scene['assignments'])
        shutil.copyfile(self.directory/'scene/scenario.xml',self.java_dir/'scenario.xml')
        config=ET.parse(self.java_dir/'config/EntityControl.xml')
        connections=next(n for n in config.iter() if n.find('TcpConnection') is not None)
        template=deepcopy(connections.find('TcpConnection'))
        for old in list(connections):
            if old.tag=='TcpConnection': connections.remove(old)
        for entity,port in self.ports['entityPorts'].items():
            node=deepcopy(template); node.set('Id',entity); node.set('Port',str(port)); connections.append(node)
        config.write(self.java_dir/'config/EntityControl.xml',encoding='utf-8',xml_declaration=True)
        config=ET.parse(self.cpp_dir/'uxas.xml'); root=config.getroot()
        template=deepcopy(root.find("Service[@Type='WaypointPlanManagerService']"))
        for node in list(root):
            if node.get('Type')=='WaypointPlanManagerService': root.remove(node)
        for entity in self.ids:
            node=deepcopy(template); node.set('VehicleID',entity); root.append(node)
        if 'area' in self.kinds and root.find("Service[@Type='SensorManagerService']") is None:
            ET.SubElement(root,'Service',Type='SensorManagerService')
        main=next(b for b in root.findall('Bridge') if b.get('Server')=='false')
        for name in ('PointSearchTask','AreaSearchTask'): ET.SubElement(main,'SubscribeToMessage',MessageType='afrl.cmasi.'+name)
        config.write(self.cpp_dir/'uxas.xml',encoding='utf-8',xml_declaration=True)
        self.item['scene']=self.scene

    def object(self,path):
        with minidom.parse(str(path)) as xml:
            factory=self.factory.LMCPFactory(); node=xml.documentElement
            obj=factory.createObjectByName(node.getAttribute('Series'),node.tagName)
            require(obj is not None,'Unknown input type'); obj.unpackFromXMLNode(node,factory); return obj

    def body(self,mode,fault,keep_gui):
        self.initial_started=time.monotonic(); self.initial_deadline=self.initial_started+30
        self.transition('initialization-started',timeoutSeconds=30)
        self.java_process=self.launch(self.java_dir,[self.java,'-Dfile.encoding=UTF-8','-Djava.awt.headless=true',
            '-Djava.io.tmpdir='+str(self.java_dir/'tmp'),'-Duser.home='+str(self.java_dir/'home'),
            '-Dg3.integration.directory='+str(self.java_dir),'-cp',os.pathsep.join(map(str,self.cp)),
            'avtas.app.Application','--config',self.java_dir/'config','--scenario','scenario.xml','--sim_rate','1'])
        self.wait('amase-paused',lambda:any(e['kind']=='initialized-paused' for e in self.amase.events(self.java_dir)))
        self.monitor=startup.Stream(startup.protocol.connect(self.ports['amasePort'],self.java_process,20),self.directory,'amase',self.factory)
        self.streams.append(self.monitor)
        self.cpp=self.launch(self.cpp_dir,[self.uxas/'uxas.exe','-cfgPath',self.cpp_dir/'uxas.xml'])
        self.observer=startup.Stream(startup.protocol.connect(self.ports['observerPort'],self.cpp,20),self.directory,'observer',self.factory)
        self.streams.append(self.observer); self.handshake()
        require(not any(r['type']=='afrl.cmasi.AirVehicleState' for r in self.observer.rows),'State before authorized start')
        (self.java_dir/'request-start').touch(); self.transition('start-authorized')
        self.item['initialData']=self.wait('all-real-initial-data',lambda:self.gate.inspect(list(self.observer.rows),list(self.monitor.rows)))
        self.port_snapshot({self.ports['amasePort']:self.java_process.pid,self.ports['observerPort']:self.cpp.pid,
                            **{p:self.java_process.pid for p in self.ports['entityPorts'].values()}},True)
        self.item['plans']=[]
        for row in self.scene['assignments']:
            task=self.object(self.directory/'scene'/row['taskFile']); self.send(task,'task')
            def initialized():
                for message in self.observer.rows: self.gate.observe_task(message)
                return self.gate.task_initialized and any(r.get('taskId')==row['taskId'] and r['type']==task.FULL_LMCP_TYPE_NAME for r in self.monitor.rows)
            self.wait('task-initialized-'+row['taskId'],initialized)
            begin=len(self.observer.rows); self.send(self.object(self.directory/'scene'/row['requestFile']),'automation-request')
            def planned():
                responses=[r for r in self.observer.rows[begin:] if r['type']=='afrl.cmasi.AutomationResponse']
                if not responses: return None
                require(len(responses)==1 and responses[0]['sourceEntity']=='100','Ambiguous planning response')
                node=ET.fromstring(base64.b64decode(responses[0]['xmlBase64']))
                plans=node.findall('MissionCommandList/MissionCommand')
                require(plans,'Empty planning response: '+ET.tostring(node,encoding='unicode'))
                require(len(plans)==1 and plans[0].findtext('VehicleID')==row['entityId'],'Request replaced a peer plan')
                points=plans[0].findall('WaypointList/Waypoint')
                require(points and any(p.findtext('AssociatedTasks/int64')==row['taskId'] for p in points),'Empty task route')
                return {'entityId':row['entityId'],'taskId':row['taskId'],'kind':row['kind'],'waypoints':len(points),
                        'rawSHA256':responses[0]['rawSHA256'],'response':responses[0]}
            self.item['plans'].append(self.wait('planning-'+row['taskId'],planned)); self.gate.planned()
        self.wait('post-planning-observation',lambda:time.monotonic()-self.initial_started>15)

    def audit(self):
        require(len(self.item['plans'])==len(self.ids),'Missing task plan')
        self.item.update(planningValidated=True,taskExecutionValidated=False,taskCompletionValidated=False,coverageValidated=False)

    def execute(self):
        self.prepare()
        for name,kinds,ids in [('point',['point'],['400']),('line',['line'],['400']),('area',['area'],['400']),
                               ('mixed',['line','point','area'],['400','500','600'])]:
            self.kinds,self.ids=kinds,ids
            # Each case receipt owns its port map; a later scene must not
            # mutate the earlier case through Startup.case's reference.
            self.config['modes']['Headless']=deepcopy(self.config['modes']['Headless'])
            self.config['modes']['Headless']['entityPorts']={i:{'400':19400,'500':19500,'600':19600}[i] for i in ids}
            case=self.case(name,'Headless'); require(case['status']=='passed',case.get('error','Planning failed'))
        require(self.inputs()==self.record['inputs'],'Diagnostic inputs changed')
        self.amase.candidate(self.root,self.args.amase_build)
        self.record.update(status='passed',planningValidated=True,inputsUnchanged=True)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--java-home',type=Path,required=True); parser.add_argument('--amase-build',required=True)
    parser.add_argument('--automatic-run',required=True)
    args=parser.parse_args(); args.root=args.root.resolve(); args.run_id='g4-t07-planning-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    args.keep_gui=False; args.mode='Headless'; args.verify=True
    directory=args.root/'out/runs'/args.run_id; directory.mkdir()
    save(directory/'context.json',{'baselineRunId':'g3-t01-check-20260919-233710-372','javaHome':str(args.java_home.resolve())})
    task=Planning(args)
    try: task.execute(); return 0
    except Exception as error: task.record.update(status='failed',error=str(error),traceback=traceback.format_exc()); return 1
    finally:
        save(directory/'result.json',task.record)
        print('G4_T07_PLANNING_RUN_ID='+args.run_id+' STATUS='+task.record['status'],flush=True)


if __name__=='__main__': sys.exit(main())
