"""Real small point/line/area flights using the unchanged formal backend."""
import argparse
import base64
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('terrain_runtime_common',Path(__file__).with_name('common.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
mixed=c.module('terrain_mixed_planning',ROOT/'scripts/g4_mixed/planning.py')
startup=mixed.startup

class TerrainRun(mixed.Planning):
    def inputs(self):
        return c.sources(self.root)

    def prepare(self):
        startup.Startup.prepare(self)
        self.record.update(task='G5-T04',scope='small-real-terrain-flight',stageQualified=False)
        self.terrain_config=c.load(self.root/'config/g5-backend-terrain.json')
        self.ids=self.terrain_config['smallEntityIds'];self.kinds=self.terrain_config['smallKinds']
        self.prepared=Path(self.context['terrainCandidate'])
        c.base.verify_files(self.prepared,c.load(self.prepared/'candidate.json')['files'])
        self.config['modes']=deepcopy(self.terrain_config['modes'])
        classes=self.root/'out/build/g5-backend'/self.args.run_id/'classes';classes.mkdir(parents=True)
        files=[self.root/p for p in ('scripts/g5_backend/TerrainProbe.java',
            'scripts/g3_execution/ExecutionProbe.java','scripts/g3_completion/CompletionProbe.java')]
        c.invoke([Path(self.context['javaHome'])/'bin/javac.exe','-encoding','UTF-8','--release','11',
            '-cp',os.pathsep.join(map(str,self.cp)),'-d',classes,*files],self.run,'terrain-javac',timeout=60)
        self.cp.append(classes)
        self.record['terrainProbeClasses']=c.base.inventory(classes,list(classes.rglob('*.class')))

    def files(self,mode,fault):
        self.mode=mode
        super().files(mode,'')
        # super builds the unchanged deterministic scene; preserve it as provenance,
        # and load the independently prepared, frozen terrain copy.
        (self.directory/'scene').rename(self.directory/'generated-unadapted-scene')
        shutil.copytree(self.prepared/'small',self.directory/'scene')
        self.scene=c.load(self.directory/'scene/scene.json')
        self.gate=mixed.gates.Gate(self.scene['assignments']);self.item['scene']=self.scene
        shutil.copy2(self.directory/'scene/scenario.xml',self.java_dir/'scenario.xml')
        shutil.copytree(self.prepared/'dted',self.java_dir/'data/g5-dted')
        plugins=ET.parse(self.java_dir/'config/Plugins.xml')
        # Install our delegating cache before TerrainConfigurator or any entity.
        plugins.getroot().insert(0,ET.Element('Plugin',Class='avtas.terrain.TerrainProbe'))
        terrain=plugins.find("Plugin[@Class='avtas.terrain.TerrainConfigurator']")
        c.need(terrain is not None,'TerrainConfigurator absent')
        ET.SubElement(ET.SubElement(terrain,'DTED'),'Directory').text='data/g5-dted'
        ET.SubElement(plugins.getroot(),'Plugin',Class='validation.g3.CompletionProbe')
        plugins.write(self.java_dir/'config/Plugins.xml',encoding='utf-8',xml_declaration=True)
        entities=ET.parse(self.java_dir/'config/EntityControl.xml')
        ET.SubElement(entities.find('DefaultAircraft'),'Module',Class='validation.g3.ExecutionProbe')
        entities.write(self.java_dir/'config/EntityControl.xml',encoding='utf-8',xml_declaration=True)
        self.item['runtimeInputs']=c.base.inventory(self.java_dir,[self.java_dir/'scenario.xml',
            *sorted((self.java_dir/'config').glob('*.xml')),*sorted((self.java_dir/'data/g5-dted').rglob('*.dt1'))])

    def launch(self,directory,argv):
        if directory==self.java_dir:
            argv=[('-Djava.awt.headless='+str(self.mode=='Headless').lower()) if str(a).startswith('-Djava.awt.headless=') else a for a in argv]
        return super().launch(directory,argv)

    def alive(self):
        super().alive()
        if self.java_dir:
            for name in ('terrain-error','analysis-error'):
                path=self.java_dir/name
                c.need(not path.exists(),name+': '+(path.read_text() if path.exists() else ''))

    def body(self,mode,fault,keep_gui):
        super().body(mode,'',False)
        c.need(c.load(self.java_dir/'terrain-loaded.json')['status']=='passed','DTED not loaded')
        expected={r['taskId']:r['entityId'] for r in self.scene['assignments']}
        completions={};cursor=0;latest=0;next_print=0
        def finished():
            nonlocal cursor,latest,next_print
            for row in self.observer.rows[cursor:]:
                cursor+=1
                if row['type']=='afrl.cmasi.SessionStatus':
                    c.need(row['realTimeMultiple']==1,'Unexpected simulation rate');latest=max(latest,int(row['timeMs']))
                if row['type']=='afrl.cmasi.AirVehicleState':
                    latest=max(latest,int(row['timeMs']))
                    node=ET.fromstring(base64.b64decode(row['xmlBase64']))
                    self.check_locations(node)
                if row['type'] in ('afrl.cmasi.AutomationResponse','afrl.cmasi.MissionCommand'):
                    self.check_locations(ET.fromstring(base64.b64decode(row['xmlBase64'])))
                if row['type']=='uxas.messages.task.TaskComplete':
                    node=ET.fromstring(base64.b64decode(row['xmlBase64']));task=node.findtext('TaskID')
                    ids=[n.text for n in node.findall('EntitiesInvolved/int64')]
                    c.need(task in expected and ids==[expected[task]] and task not in completions and row['sourceEntity']=='100','Wrong or repeated completion')
                    completions[task]=dict(entityId=ids[0],timeMs=node.findtext('TimeTaskCompleted'),message=row)
            if time.monotonic()>=next_print:
                print('G5 terrain '+mode+': simulation='+str(latest)+' ms; completed='+str(len(completions))+'/3',flush=True)
                next_print=time.monotonic()+30
            c.need(latest<1795000,'Small terrain tasks did not complete within frozen duration')
            return len(completions)==3 and latest>=max(int(v['timeMs']) for v in completions.values())+3000
        self.wait('terrain-task-completions',finished,1900)
        self.item['observedCompletions']=completions;self.item['lastSimulationMs']=str(latest)
        (self.java_dir/'request-pause').touch()
        self.wait('terrain-flight-paused',lambda:any(e['kind']=='paused' for e in self.amase.events(self.java_dir)))
        (self.java_dir/'request-analysis').touch()
        self.wait('terrain-analysis-exported',lambda:(self.java_dir/'analysis-done').exists(),90)

    def check_locations(self,node):
        locations=[node.find('Location/Location3D')] if node.tag=='AirVehicleState' else list(node.iter())
        for p in locations:
            if p is None:continue
            if p.find('Latitude') is None or p.find('Longitude') is None:continue
            lat,lon=float(p.findtext('Latitude')),float(p.findtext('Longitude'))
            # Camera centerpoint/corner fields have legacy planar or stale-height
            # semantics; aircraft and planned positions are the flight boundary.
            c.need(45<=lat<46 and -122<=lon<-120,'Actual planned/observed geometry outside qualified region')

    def audit(self):
        super().audit()
        c.need((self.java_dir/'analysis-done').exists() and self.item.get('observedCompletions'),'Missing real terrain completion')
        c.need(not (self.java_dir/'terrain-error').exists(),'Invalid terrain query')
        summary=c.load(self.java_dir/'terrain-summary.json')
        for name in ('KinematicFlight','CameraControl','SearchTaskAnalysis'):
            c.need(any(name in key and count>0 for key,count in summary['calls'].items()),'Missing actual terrain caller '+name)
        c.need(summary['minimum']>0 and summary['intercepts']>0,'No real nonzero terrain participation')
        c.base.verify_files(self.java_dir,self.item['runtimeInputs'])
        self.item.update(realTerrainFlightCaptured=True,independentAuditRequired=True,terrainSummary=summary)

    def execute(self):
        self.prepare()
        for mode in self.args.modes:
            self.operation_deadline=time.monotonic()+2650
            case=self.case(mode.lower(),mode)
            c.need(case['status']=='passed',case.get('error','Terrain run failed'))
        c.need(self.inputs()==self.record['inputs'],'Runtime sources changed')
        self.amase.verify_records(self.root,self.baseline['frozenInputs'])
        self.record.update(status='passed',inputsUnchanged=True,backendTerrainExecutionQualified=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);parser.add_argument('--modes',nargs='+',choices=['Gui','Headless'],required=True)
    args=parser.parse_args();args.root=ROOT;args.keep_gui=False;args.verify=False
    task=TerrainRun(args)
    try:task.execute();return 0
    except Exception as error:task.record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(str(error),flush=True);return 1
    finally:c.save(task.run/'result.json',task.record)

if __name__=='__main__':sys.exit(main())
