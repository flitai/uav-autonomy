"""G5-T10: twenty real terrain aircraft, formal gateway and Cesium for thirty minutes."""
import argparse
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

ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

scale=module('g5_scale_g4',ROOT/'scripts/g4_scale/runtime.py')
g5=module('g5_scale_coverage',ROOT/'scripts/g5_coverage/runtime.py')
checks=module('g5_scale_terrain_checks',ROOT/'tests/g5_backend/checks.py')
statistics=module('g5_scale_terrain_statistics',ROOT/'tests/g5_scale/statistics.py')
execution=module('g5_scale_execution',ROOT/'scripts/g4_mixed/execution.py')
handoff=module('g5_scale_handoff',ROOT/'tests/g5_scale/handoff.py')
performance=module('g5_scale_performance',ROOT/'scripts/g4_scale/performance.py')
gpu=module('g5_scale_gpu',Path(__file__).with_name('gpu.py'))
c=g5.c


def rows(path):return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


class ScaleRun(scale.Scale):
    def inputs(self):
        paths=[p for folder in ('scripts/g5_scale','tests/g5_scale') for p in (ROOT/folder).rglob('*')
               if p.is_file() and '__pycache__' not in p.parts]
        paths.extend(ROOT/p for p in ('tests/windows/g5-scale.tests.ps1',
            'tests/g5_backend/checks.py','tests/g5_backend/statistics.py',
            'scripts/g5_backend/TerrainProbe.java','scripts/g4_scale/performance.py',
            'tests/g5_full/handoff.py'))
        return super().inputs()+g5.c.sources()+c.base.inventory(ROOT,paths)

    def prepare(self):
        super().prepare()
        self.record.update(task='G5-T10',scope='twenty-real-terrain-thirty-minute-cesium',
                           scaleDisplayQualified=False,stageQualified=False)
        self.prepared=Path(self.context['terrainCandidate'])
        c.base.verify_files(self.prepared,c.load(self.prepared/'candidate.json')['files'])
        scene=c.load(self.prepared/'mixed20/scene.json')
        c.need(len(scene['assignments'])==20 and
               [row['kind'] for row in scene['assignments']]==['line']*8+['point']*6+['area']*6 and
               len({row['entityId'] for row in scene['assignments']})==20 and
               len({row['taskId'] for row in scene['assignments']})==20,
               'Frozen mixed20 terrain scene differs')
        self.terrain=checks.Terrain(self.prepared)
        self.args.bundle,pointer,self.web_python=g5.state.entry.resolve(ROOT)
        self.package_sha=c.sha(self.args.bundle/'package.json')
        self.node=(ROOT/c.load(ROOT/'.tools/g5/current.json')['path'])/'node/node.exe'
        self.record.update(gatewayPointer=pointer,packageSHA256=self.package_sha,
                           terrainCandidateSHA256=c.sha(self.prepared/'candidate.json'))
        classes=ROOT/'out/build/g5-scale'/self.args.run_id/'classes';classes.mkdir(parents=True)
        c.invoke([Path(self.context['javaHome'])/'bin/javac.exe','-encoding','UTF-8','--release','11',
                  '-cp',os.pathsep.join(map(str,self.cp)),'-d',classes,
                  ROOT/'scripts/g5_backend/TerrainProbe.java'],self.run,'terrain-javac',timeout=60)
        self.cp.append(classes)
        self.record['terrainProbeClasses']=c.base.inventory(classes,list(classes.rglob('*.class')))

    def files(self,mode,fault):
        self.browser=None;self.browser_stopping=False;self.browser_command=0;self.collector=None
        self.gpu_observer=None;self.browser_dir=self.directory/'browser'
        super().files(mode,'')
        (self.directory/'scene').rename(self.directory/'generated-unadapted-scene')
        shutil.copytree(self.prepared/'mixed20',self.directory/'scene')
        self.scene=c.load(self.directory/'scene/scene.json');self.item['scene']=self.scene
        shutil.copy2(self.directory/'scene/scenario.xml',self.java_dir/'scenario.xml')
        shutil.copytree(self.prepared/'dted',self.java_dir/'data/g5-dted')
        plugins=ET.parse(self.java_dir/'config/Plugins.xml')
        plugins.getroot().insert(0,ET.Element('Plugin',Class='avtas.terrain.TerrainProbe'))
        configurator=plugins.find("Plugin[@Class='avtas.terrain.TerrainConfigurator']")
        c.need(configurator is not None,'TerrainConfigurator missing')
        ET.SubElement(ET.SubElement(configurator,'DTED'),'Directory').text='data/g5-dted'
        plugins.write(self.java_dir/'config/Plugins.xml',encoding='utf-8',xml_declaration=True)
        self.item['runtimeInputs']=c.base.inventory(self.java_dir,[self.java_dir/'scenario.xml',
            *sorted((self.java_dir/'config').glob('*.xml')),
            *sorted((self.java_dir/'data/g5-dted').rglob('*.dt1'))])
        self.browser_sampler=scale.metrics.Sampler(self.directory/'browser-resources.jsonl')

    def handshake(self):
        scale.startup.Startup.handshake(self)
        ports={'amase':15555,'uxas':19999}
        for name,upstream in [('amase',self.ports['amasePort']),('uxas',self.ports['observerPort'])]:
            self.amase.check_port(ports[name]);self.proxies[name]=scale.proxy.ObserverProxy(ports[name],upstream)
        self.host=g5.state.stage.TwentyHost(self,self.web_python,self.schema,ports);self.host.start()
        self.collector=g5.collector.Collector(self.directory/'gateway-host/manifest.json',
                                               self.prepared,self.run/'coverage/live.json')
        self.collector.start()
        self.watch_directory=self.directory/'continuous-clients'
        with (self.directory/'watch.stdout').open('wb') as stdout,(self.directory/'watch.stderr').open('wb') as stderr:
            self.watcher=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',
                str(ROOT/'tests/g4_scale/watch.py'),'--url',self.host.url,
                '--run-id',self.host.manifest['run_id'],'--output',str(self.watch_directory)],
                stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)

    def transition(self,phase,**evidence):
        super().transition(phase,**evidence)
        if phase=='three-clients' and self.browser is None:
            with (self.directory/'browser.stdout').open('wb') as stdout,(self.directory/'browser.stderr').open('wb') as stderr:
                self.browser=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',
                    str(ROOT/'tests/g5_scale/browser.py'),'--output',str(self.browser_dir),
                    '--url','http://127.0.0.1:8080'],cwd=self.directory,stdout=stdout,stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            self.gpu_observer=gpu.Observer(self.browser.pid,self.directory/'gpu-resources.jsonl')
            self.gpu_observer.start()
            self.wait('cesium-browser-open',lambda:(self.browser_dir/'opened').exists() or
                      self.browser.poll() is not None,60)
            c.need(self.browser.poll() is None,'Cesium browser failed during scale startup')

    def status(self):
        path=self.browser_dir/'status.json'
        return c.load(path) if path.exists() else {}

    def browser_ready(self,seconds=90):
        def ready():
            c.need(self.browser.poll() is None,'Scale browser stopped')
            status=self.status();identity=status.get('identity') or {}
            return (status.get('phase')=='live' and identity.get('run_id')==self.host.manifest['run_id'] and
                    identity.get('stream_id')==self.host.health()['stream_id'] and
                    status.get('coverageRunId')==identity.get('run_id') and
                    status.get('entityObjects')==20 and status.get('missionObjects',0)>0 and
                    status.get('counts',{}).get('tasks')==20 and status.get('coverageTasks')==20)
        self.wait('cesium-browser-final-ready',ready,seconds)
        return self.status()

    def command(self,action,seconds=50):
        number=self.browser_command;self.browser_command+=1
        path=self.browser_dir/'commands'/f'{number:03d}.json';path.parent.mkdir(exist_ok=True)
        c.save(path,{'action':action})
        receipt=self.browser_dir/'responses'/f'{number:03d}.json'
        self.wait('cesium-browser-'+action+'-'+str(number),
                  lambda:receipt.exists() or self.browser.poll() is not None,seconds)
        c.need(receipt.exists() and c.load(receipt)['status']=='passed','Browser command failed: '+action)
        return number

    def alive(self):
        super().alive()
        if self.java_dir:
            for name in ('terrain-error','analysis-error'):
                path=self.java_dir/name
                c.need(not path.exists(),name+': '+(path.read_text(encoding='utf-8') if path.exists() else ''))
        if self.browser and not self.browser_stopping:
            c.need(self.browser.poll() is None,'Cesium browser exited during scale run')
            if self.host and self.host.current and self.host.current[2].poll() is None:
                health=self.host.health()
                if health and time.monotonic()>=self.browser_sampler.next:
                    self.browser_sampler.sample({'browser':self.browser.pid},health,health['source_time_ms'])

    def body(self,mode,fault,keep_gui):
        super().body(mode,'',False)
        self.item['flightFinishedAt']=scale.startup.stamp()
        snapshot=self.host.live();self.browser_ready(90)
        self.wait('cesium-all-complete',lambda:len(self.status().get('completed',[]))==20,75)
        capture=self.command('capture')
        page=c.load(self.browser_dir/f'capture-{capture:03d}.json')
        c.need(page['business']['state']==snapshot['state'],'Twenty-aircraft browser differs from gateway snapshot')
        c.need(page['coverage']['snapshot']['runId']==snapshot['run_id'] and
               len(page['coverage']['snapshot']['tasks'])==20,'Twenty-aircraft coverage identity/count differs')
        self.item['browserSummary']=page['summary']
        self.item['browserCoverageTaskCount']=len(page['coverage']['snapshot']['tasks'])
        self.item['gpuObserver']=self.gpu_observer.stop()
        c.need(self.item['gpuObserver']['status']=='passed','GPU resource sampling failed')
        self.browser_stopping=True;self.command('stop')
        self.wait('cesium-browser-exit',lambda:self.browser.poll() is not None,50)
        result=c.load(self.browser_dir/'result.json')
        c.need(self.browser.returncode==0 and result['status']=='passed' and not result['forcedTermination'],
               'Cesium browser did not exit normally')
        self.item['browser']=result

    def cleanup(self):
        try:
            if self.gpu_observer and self.gpu_observer.thread.is_alive():
                receipt=self.gpu_observer.stop();self.item['gpuObserver']=receipt
                if receipt['status']!='passed':self.item.setdefault('cleanupErrors',[]).append('GPU observer failed')
            if self.browser and self.browser.poll() is None:
                self.browser_stopping=True
                try:self.command('stop',20)
                except Exception:self.item.setdefault('cleanupErrors',[]).append('Cesium browser normal stop failed')
                try:self.browser.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    self.browser.kill();self.browser.wait();self.item.setdefault('cleanupErrors',[]).append('Cesium browser forced termination')
            if self.collector:
                receipt=self.collector.stop();self.item['coverageCollector']=receipt
                if receipt['status']!='passed':self.item.setdefault('cleanupErrors',[]).append('Coverage worker failed')
        finally:super().cleanup()

    def audit(self):
        super().audit()
        c.need(self.item.get('browser',{}).get('status')=='passed' and
               self.item.get('coverageCollector',{}).get('status')=='passed' and
               self.item.get('gpuObserver',{}).get('status')=='passed',
               'Browser, coverage or GPU receipt missing')
        c.need(c.load(self.java_dir/'terrain-loaded.json')['status']=='passed','Real terrain not loaded')
        summary=c.load(self.java_dir/'terrain-summary.json')
        c.need(summary['minimum']>0 and summary['intercepts']>0 and
               all(any(name in key and count>0 for key,count in summary['calls'].items())
                   for name in ('KinematicFlight','CameraControl','SearchTaskAnalysis')),
               'Real terrain callers missing')
        c.base.verify_files(self.java_dir,self.item['runtimeInputs'])
        bus=rows(self.directory/'observer.jsonl');wire=rows(self.directory/'amase.jsonl')
        events=rows(self.java_dir/'events.jsonl')
        nav=[row for path in sorted(self.java_dir.glob('execution-*.jsonl')) for row in rows(path)]
        bus,nav,episodes=handoff.normalize(ROOT,bus,wire,events,nav,self.scene['assignments'])
        c.save(self.directory/'segment-handoffs.json',episodes)
        requests={row['taskId']:ET.fromstring(self.object(self.directory/'scene'/row['requestFile']).toXMLStr(''))
                  for row in self.scene['assignments']}
        proof=execution.assess(ROOT,bus,wire,events,nav,self.scene['assignments'],requests)
        c.save(self.directory/'independent-execution.json',proof)
        stats=statistics.inspect(ROOT,self.directory,self.scene['assignments'],self.terrain)
        c.save(self.directory/'independent-statistics.json',stats)
        capture=c.load(sorted(self.browser_dir.glob('capture-*.json'))[-1])
        display={str(row['taskId']):row for row in capture['coverage']['snapshot']['tasks']}
        c.need(len(display)==20,'Browser coverage task identity differs')
        for row in stats['tasks']:
            shown=display[row['taskId']]
            if row['kind']=='point':
                c.need(shown['observationMilliseconds']==row['observationMilliseconds'],
                       'Browser/native point observation differs: '+row['taskId'])
            else:
                c.need(shown['seenCells']==row['seenCells'] and shown['totalCells']==row['totalCells'],
                       'Browser/native twenty-task coverage differs: '+row['taskId'])
        performance_case=dict(self.item,finishedAt=self.item['flightFinishedAt'])
        perf=performance.inspect(self.directory,performance_case)
        c.save(self.directory/'performance.json',perf)
        browser_samples=c.load(self.browser_dir/'samples.json')
        c.need(len(browser_samples)>=330,'Insufficient thirty-minute browser samples')
        browser_metrics={name:performance.quantiles([float(row[name]) for row in browser_samples if row.get(name) is not None])
                         for name in ('frameP50Ms','frameP95Ms','jsHeapUsedBytes','jsHeapTotalBytes',
                                      'entityObjects','missionObjects','currentObjects','accumulatedObjects')}
        gpu_rows=rows(self.directory/'gpu-resources.jsonl')
        c.need(len(gpu_rows)>=10 and any(int(row['localBytes'])>0 for row in gpu_rows),
               'Long GPU resource samples missing')
        gpu_metrics={name:performance.quantiles([float(row[name]) for row in gpu_rows])
                     for name in ('localBytes','engineUtilizationSumPercent','engineUtilizationPeakPercent')}
        c.save(self.directory/'browser-performance.json',dict(status='passed',
            browser=browser_metrics,gpu=gpu_metrics,renderer=self.item['browserSummary']['renderer'],
            viewport=self.item['browserSummary']['viewport'],canvas=self.item['browserSummary']['canvas'],
            modelRequests=self.item['browser']['modelRequests'],sampleCount=len(browser_samples)))
        self.item.update(terrainSummary=summary,independentExecution=True,independentStatistics=True,
                         browserPerformanceSamples=len(browser_samples),gpuSamples=len(gpu_rows),
                         scaleDisplayQualified=True)

    def execute(self):
        self.prepare();candidate=Path(self.context['stateCandidate'])
        for mode in ('Headless','Gui'):
            output=self.run/('map-service-'+mode.lower())
            with g5.state.services.running([self.node,ROOT/'scripts/g5_coverage/server.mjs',
                    candidate/'service.json',output,self.run/'coverage/live.json'],output):
                self.config['modes'][mode]=deepcopy(self.config['modes'][mode])
                offset=10000 if mode=='Headless' else 0
                self.config['modes'][mode]['entityPorts']={entity:9000+int(entity)+offset for entity in scale.IDS}
                self.started=time.monotonic();self.operation_deadline=self.started+2650
                result=self.case('scale-'+mode.lower(),mode)
                c.need(time.monotonic()-self.started<=2700,'Thirty-minute mode exceeded automatic budget')
                c.need(result['status']=='passed' and result.get('scaleDisplayQualified'),
                       result.get('error','Twenty-aircraft case failed'))
        c.need(self.inputs()==self.record['inputs'],'T10 inputs changed')
        self.amase.verify_records(ROOT,self.baseline['frozenInputs'])
        self.record.update(status='passed',scaleDisplayQualified=True,stageQualified=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True)
    args=parser.parse_args();args.root=ROOT;args.keep_gui=False;args.verify=False
    args.modes=['Headless','Gui'];args.mode='Headless';args.seconds=1800
    task=ScaleRun(args)
    try:task.execute();return 0
    except Exception as error:
        task.record.update(status='failed',error=str(error),traceback=traceback.format_exc())
        print(task.record['traceback'],flush=True);return 1
    finally:c.save(task.run/'runtime-result.json',task.record)

if __name__=='__main__':sys.exit(main())
