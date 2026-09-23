"""G5-T09 original WaterwaySearch with the qualified terrain and real Cesium page."""
import argparse
import base64
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import xml.dom.minidom
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

g3=module('g5_full_g3',ROOT/'scripts/g3_completion/runtime.py')
g5=module('g5_full_g5',ROOT/'scripts/g5_coverage/runtime.py')
terrain_checks=module('g5_full_terrain_checks',ROOT/'tests/g5_backend/checks.py')
terrain_stats=module('g5_full_terrain_stats',ROOT/'tests/g5_backend/statistics.py')
handoff=module('g5_full_handoff',ROOT/'tests/g5_full/handoff.py')
c=g5.c


class FullRun(g3.Completion):
    def inputs(self):
        paths=[p for folder in ('scripts/g5_full','tests/g5_full') for p in (ROOT/folder).rglob('*')
               if p.is_file() and '__pycache__' not in p.parts]
        paths.extend(ROOT/p for p in ('tests/windows/g5-full.tests.ps1',
            'tests/g5_lifecycle/browser.py','scripts/g5_backend/TerrainProbe.java',
            'tests/g5_backend/checks.py','tests/g5_backend/statistics.py'))
        return super().inputs()+c.sources()+c.base.inventory(ROOT,paths)

    def prepare(self):
        super().prepare()
        self.record.update(task='G5-T09',scope='original-two-entity-full-real-terrain-browser',
                           fullSimulationDisplayQualified=False,stageQualified=False)
        self.prepared=Path(self.context['terrainCandidate'])
        c.base.verify_files(self.prepared,c.load(self.prepared/'candidate.json')['files'])
        self.scene=c.load(self.prepared/'original/scene.json')
        c.need(self.scene['purpose']=='original-two-entity-terrain-copy' and
               [(r['entityId'],r['taskId']) for r in self.scene['assignments']]==[('400','1000'),('500','1000')],
               'Original two-entity scene differs')
        self.terrain=terrain_checks.Terrain(self.prepared)
        self.args.bundle,pointer,self.web_python=g5.state.entry.resolve(ROOT)
        self.package_sha=c.sha(self.args.bundle/'package.json')
        self.schema=g5.state.stage.original.load_schema(ROOT)
        self.node=(ROOT/c.load(ROOT/'.tools/g5/current.json')['path'])/'node/node.exe'
        self.record.update(gatewayPointer=pointer,packageSHA256=self.package_sha,
                           terrainCandidateSHA256=c.sha(self.prepared/'candidate.json'))
        classes=ROOT/'out/build/g5-full'/self.args.run_id/'classes';classes.mkdir(parents=True)
        c.invoke([Path(self.context['javaHome'])/'bin/javac.exe','-encoding','UTF-8','--release','11',
                  '-cp',os.pathsep.join(map(str,self.cp)),'-d',classes,
                  ROOT/'scripts/g5_backend/TerrainProbe.java'],self.run,'terrain-javac',timeout=60)
        self.cp.append(classes)
        self.record['terrainProbeClasses']=c.base.inventory(classes,list(classes.rglob('*.class')))

    def files(self,mode,fault):
        self.mode=mode;self.host=None;self.collector=None;self.browser=None;self.browser_command=0
        super().files(mode,'')
        shutil.copytree(self.prepared/'original',self.directory/'scene')
        shutil.copy2(self.directory/'scene/scenario.xml',self.java_dir/'scenario.xml')
        shutil.copytree(self.prepared/'dted',self.java_dir/'data/g5-dted')
        plugins=ET.parse(self.java_dir/'config/Plugins.xml')
        plugins.getroot().insert(0,ET.Element('Plugin',Class='avtas.terrain.TerrainProbe'))
        configurator=plugins.find("Plugin[@Class='avtas.terrain.TerrainConfigurator']")
        c.need(configurator is not None,'TerrainConfigurator missing')
        ET.SubElement(ET.SubElement(configurator,'DTED'),'Directory').text='data/g5-dted'
        plugins.write(self.java_dir/'config/Plugins.xml',encoding='utf-8',xml_declaration=True)
        self.item['scene']=self.scene
        self.item['runtimeInputs']=c.base.inventory(self.java_dir,[self.java_dir/'scenario.xml',
            *sorted((self.java_dir/'config').glob('*.xml')),
            *sorted((self.java_dir/'data/g5-dted').rglob('*.dt1'))])

    def input_message(self,key):
        if key not in ('task','request'):return super().input_message(key)
        name='task-1000.xml' if key=='task' else 'request-1000.xml'
        node=xml.dom.minidom.parse(str(self.prepared/'original'/name)).documentElement
        factory=self.factory.LMCPFactory()
        obj=factory.createObjectByName(node.getAttribute('Series'),node.localName)
        c.need(obj is not None,'Original terrain '+key+' cannot be decoded')
        obj.unpackFromXMLNode(node,factory)
        return obj

    def handshake(self):
        super().handshake()
        self.host=g5.state.stage.TwentyHost(self,self.web_python,self.schema,
            {'amase':self.ports['amasePort'],'uxas':self.ports['observerPort']})
        self.host.start()
        self.collector=g5.collector.Collector(self.directory/'gateway-host/manifest.json',
                                               self.prepared,self.run/'coverage/live.json')
        self.collector.start()

    def status(self):
        path=self.browser_dir/'status.json'
        return c.load(path) if path.exists() else {}

    def browser_ready(self,stream=None,seconds=80):
        def ready():
            c.need(self.browser.poll() is None,'Browser stopped during full task')
            s=self.status();identity=s.get('identity') or {}
            return (s.get('phase')=='live' and identity.get('run_id')==self.host.manifest['run_id'] and
                    (stream is None or identity.get('stream_id')==stream) and s.get('coverageRunId')==identity.get('run_id')
                    and s.get('entityObjects')==2 and s.get('missionObjects',0)>0 and
                    s.get('counts',{}).get('tasks')==1 and '1000' in (s.get('coverageTasks') or []))
        self.wait('full-browser-live',ready,seconds)
        return self.status()

    def command(self,action,seconds=40):
        number=self.browser_command;self.browser_command+=1
        path=self.browser_dir/'commands'/f'{number:03d}.json';path.parent.mkdir(exist_ok=True)
        c.save(path,{'action':action})
        receipt=self.browser_dir/'responses'/f'{number:03d}.json'
        self.wait('full-browser-'+action+'-'+str(number),
                  lambda:receipt.exists() or self.browser.poll() is not None,seconds)
        c.need(receipt.exists() and c.load(receipt)['status']=='passed','Browser command failed: '+action)
        return number

    def body(self,mode,fault,keep_gui):
        self.browser_dir=self.directory/'browser'
        with (self.directory/'browser.stdout').open('wb') as stdout,(self.directory/'browser.stderr').open('wb') as stderr:
            self.browser=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',
                str(ROOT/'tests/g5_lifecycle/browser.py'),'--output',str(self.browser_dir),
                '--url','http://127.0.0.1:8080'],cwd=self.directory,stdout=stdout,stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('full-browser-open',lambda:(self.browser_dir/'opened').exists() or self.browser.poll() is not None,55)
        c.need(self.browser.poll() is None,'Browser failed before backend start')
        g3.execution.startup.Startup.body(self,mode,'',False)
        initial=self.host.live();self.browser_ready(initial['stream_id'])
        self.item['firstBrowser']=self.status()
        old_origin=self.status()['pageOrigin'];self.command('refresh')
        self.wait('full-refresh',lambda:self.status().get('pageOrigin')!=old_origin and
                  self.status().get('snapshots',0)>=1,65)
        self.browser_ready(initial['stream_id'])
        self.host.stop()
        self.wait('full-gateway-disconnected',lambda:self.status().get('phase') in
                  ('recovering','degraded','waiting-snapshot','connecting'),35)
        self.host.start();restored=self.host.live()
        c.need(restored['run_id']==initial['run_id'] and restored['stream_id']!=initial['stream_id'],
               'Full task gateway reconnect identity differs')
        self.browser_ready(restored['stream_id'])
        self.item['reconnect']=dict(before=initial['stream_id'],after=restored['stream_id'])
        cursor=0;complete_ms=None;latest=0;next_log=0
        def finished():
            nonlocal cursor,complete_ms,latest,next_log
            for row in self.observer.rows[cursor:]:
                cursor+=1
                if row['type']=='afrl.cmasi.AirVehicleState':latest=max(latest,int(row['timeMs']))
                if row['type']=='uxas.messages.task.TaskComplete':
                    c.need(complete_ms is None,'Repeated original TaskComplete')
                    node=ET.fromstring(base64.b64decode(row['xmlBase64']))
                    assigned=sorted(command['vehicleId'] for command in self.item['planningReceipt']['commands'])
                    c.need(assigned and len(assigned)==len(set(assigned)) and set(assigned)<={'400','500'},
                           'Original planning assignment differs')
                    c.need(node.findtext('TaskID')=='1000' and
                           sorted(n.text for n in node.findall('EntitiesInvolved/int64'))==assigned,
                           'Original completion identity differs')
                    complete_ms=int(node.findtext('TimeTaskCompleted'))
            if time.monotonic()>=next_log:
                print('G5 full '+mode+': simulation='+str(latest)+' ms; complete='+str(complete_ms),flush=True)
                next_log=time.monotonic()+30
            c.need(latest<785000,'Original full task exceeded frozen duration')
            return complete_ms is not None and latest>=complete_ms+3000
        self.wait('full-task-complete',finished,830)
        self.item['completionTimeMs']=str(complete_ms)
        (self.java_dir/'request-pause').touch()
        self.wait('full-backend-paused',lambda:any(e['kind']=='paused' for e in self.amase.events(self.java_dir)))
        (self.java_dir/'request-analysis').touch()
        self.wait('full-native-analysis',lambda:(self.java_dir/'analysis-done').exists(),90)
        snapshot=self.host.live()
        self.wait('full-browser-completion',lambda:'1000' in self.status().get('completed',[]),45)
        capture=self.command('capture')
        page=c.load(self.browser_dir/f'capture-{capture:03d}.json')
        c.need(page['business']['state']==snapshot['state'],'Full page differs from gateway snapshot')
        c.need(page['coverage']['snapshot']['runId']==snapshot['run_id'],'Full coverage run differs')
        c.need(page['summary']['entityObjects']==2 and page['summary']['missionObjects']>0,
               'Original aircraft or mission was not rendered')
        self.item['finalBrowser']=dict(summary=page['summary'],
                                       stateSHA256=c.base.digest_json(page['business']['state']) if hasattr(c.base,'digest_json') else None)
        self.command('stop');self.wait('full-browser-exit',lambda:self.browser.poll() is not None,45)
        browser=c.load(self.browser_dir/'result.json')
        c.need(self.browser.returncode==0 and browser['status']=='passed' and not browser['forcedTermination'],
               'Full browser did not exit normally')
        self.item['browser']=browser
        self.host.stop()

    def cleanup(self):
        try:
            if self.browser and self.browser.poll() is None:
                try:self.command('stop',15)
                except Exception:self.item.setdefault('cleanupErrors',[]).append('Browser normal stop failed')
            if self.host and self.host.current:self.host.stop()
            if self.collector:
                receipt=self.collector.stop();self.item['coverageCollector']=receipt
                if receipt['status']!='passed':self.item.setdefault('cleanupErrors',[]).append('Coverage worker failed')
        finally:super().cleanup()

    def audit(self):
        g3.execution.startup.Startup.audit(self)
        c.need(self.item.get('browser',{}).get('status')=='passed' and self.host.records and
               all(r['status']=='passed' for r in self.host.records),'Full gateway/browser acceptance missing')
        c.need(c.load(self.java_dir/'terrain-loaded.json')['status']=='passed','Real DTED not loaded')
        summary=c.load(self.java_dir/'terrain-summary.json')
        c.need(summary['minimum']>0 and summary['intercepts']>0 and
               all(any(name in key and count>0 for key,count in summary['calls'].items())
                   for name in ('KinematicFlight','CameraControl','SearchTaskAnalysis')),
               'Real terrain callers missing')
        assigned_plan=[command['vehicleId'] for command in self.item['planningReceipt']['commands']]
        c.need(len(assigned_plan)==1,'Original planning cardinality changed')
        navigation,episodes=handoff.normalize(self.observer.rows,self.navigation(),assigned_plan[0])
        self.item['segmentHandoffs']=episodes
        evidence=g3.completion.assess(self.observer.rows,self.monitor.rows,self.amase.events(self.java_dir),
             self.policy,ET.fromstring(self.input_message('request').toXMLStr('')),navigation)
        c.save(self.directory/'completion.json',evidence)
        assigned=evidence['assignedEntities']
        c.need(len(assigned)==1 and assigned[0] in ('400','500'),'Original assignment cardinality changed')
        stats_row=next(row for row in self.scene['assignments'] if row['entityId']==assigned[0])
        stats=terrain_stats.inspect(ROOT,self.directory,[stats_row],self.terrain)
        c.save(self.directory/'independent-statistics.json',stats)
        c.base.verify_files(self.java_dir,self.item['runtimeInputs'])
        self.item.update(completion=dict(taskId=evidence['taskId'],assignedEntities=evidence['assignedEntities'],
                                  completion=evidence['completion'],entities=evidence['entities']),
                         statistics=stats,terrainSummary=summary,fullSimulationDisplayQualified=True)
        self.item['planningReceipt']['actualExecutionValidated']=True

    def execute(self):
        self.prepare();candidate=Path(self.context['stateCandidate'])
        for mode in ('Headless','Gui'):
            output=self.run/('map-service-'+mode.lower())
            with g5.state.services.running([self.node,ROOT/'scripts/g5_coverage/server.mjs',
                    candidate/'service.json',output,self.run/'coverage/live.json'],output):
                self.operation_deadline=time.monotonic()+2650
                item=self.case('full-'+mode.lower(),mode)
                c.need(item['status']=='passed' and item.get('fullSimulationDisplayQualified'),
                       item.get('error','Original full task failed'))
        c.need(self.inputs()==self.record['inputs'],'Full task sources changed')
        self.amase.verify_records(ROOT,self.baseline['frozenInputs'])
        self.record.update(status='passed',taskExecutionValidated=True,taskCompletionValidated=True,
                           coverageValidated=True,fullSimulationDisplayQualified=True,stageQualified=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True)
    args=parser.parse_args();args.root=ROOT;args.verify=False;args.keep_gui=False
    task=FullRun(args)
    try:task.execute();return 0
    except Exception as error:
        task.record.update(status='failed',error=str(error),traceback=traceback.format_exc())
        print(task.record['traceback'],flush=True);return 1
    finally:c.save(task.run/'runtime-result.json',task.record)

if __name__=='__main__':sys.exit(main())
