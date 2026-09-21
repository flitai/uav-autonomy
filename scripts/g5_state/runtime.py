"""Real qualified terrain backends and published G4 gateway, observed by Edge."""
import argparse
import base64
import importlib.util
from pathlib import Path
import subprocess
import socket
import struct
import sys
import time
import traceback
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('g5_state_runtime_common',Path(__file__).with_name('common.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
terrain=c.module('g5_state_terrain_runtime',ROOT/'scripts/g5_backend/runtime.py')
stage=c.module('g5_state_gateway_runtime',ROOT/'scripts/g4_stage/runtime.py')
entry=c.module('g5_state_gateway_entry',ROOT/'scripts/g4_stage/entry.py')
services=c.module('g5_state_service_lifecycle',ROOT/'tests/g5_map/checks.py')

class StateRun(terrain.TerrainRun):
    def inputs(self):return c.sources(self.root)
    def prepare(self):
        super().prepare()
        self.args.bundle,pointer,self.web_python=entry.resolve(self.root)
        self.package_sha=c.sha(self.args.bundle/'package.json')
        self.schema=stage.original.load_schema(self.root)
        self.record.update(task='G5-T05',scope='real-state-connection',gatewayPointer=pointer,packageSHA256=self.package_sha)
        self.node=(self.root/c.load(self.root/'.tools/g5/current.json')['path'])/'node/node.exe'

    def files(self,mode,fault):
        self.host=None;self.browser=None
        super().files(mode,fault)

    def handshake(self):
        super().handshake()
        self.host=stage.TwentyHost(self,self.web_python,self.schema,{'amase':self.ports['amasePort'],'uxas':self.ports['observerPort']})
        self.host.start()

    def body(self,mode,fault,keep_gui):
        self.browser_dir=self.directory/'browser'
        with (self.directory/'browser.stdout').open('wb') as stdout,(self.directory/'browser.stderr').open('wb') as stderr:
            self.browser=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',str(ROOT/'tests/g5_state/browser.py'),
                '--output',str(self.browser_dir),'--url','http://127.0.0.1:8080'],cwd=self.directory,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('browser-before-backend',lambda:(self.browser_dir/'opened').exists() or self.browser.poll() is not None,40)
        c.need(self.browser.poll() is None,'Browser failed before backend started')
        terrain.mixed.Planning.body(self,mode,'',False)
        self.host.live()
        self.wait('browser-initial-late-refresh',lambda:(self.browser_dir/'request-pause').exists() or self.browser.poll() is not None,150)
        c.need(self.browser.poll() is None,'Browser failed before stable comparison')
        (self.java_dir/'request-pause').touch()
        self.wait('state-paused',lambda:any(r['kind']=='paused' for r in self.amase.events(self.java_dir)))
        (self.java_dir/'request-analysis').touch()
        self.wait('state-analysis',lambda:(self.java_dir/'analysis-done').exists(),60)
        self.wait('browser-snapshot-comparison',lambda:(self.browser_dir/'verified').exists() or self.browser.poll() is not None,60)
        c.need(self.browser.poll() is None,'Browser failed while comparing stable snapshots')
        self.item['snapshot']=self.host.live()
        # Closing the observer exercises real 503/stream loss while the paused backend stays alive.
        self.host.stop();(self.browser_dir/'gateway-stopped').touch()
        self.wait('browser-normal-exit',lambda:self.browser.poll() is not None,60)
        c.need(self.browser.returncode==0,'Browser acceptance failed')
        browser=c.load(self.browser_dir/'result.json');c.need(browser['status']=='passed','Browser receipt failed')
        self.item.update(browser=browser,realStateConnectionQualified=True)

    def cleanup(self):
        if getattr(self,'browser',None) and self.browser.poll() is None:
            (self.browser_dir/'request-stop').touch()
            try:self.browser.wait(timeout=35)
            except subprocess.TimeoutExpired:
                self.browser.kill();self.browser.wait();self.item.setdefault('cleanupErrors',[]).append('Browser forced termination')
        if getattr(self,'host',None) and self.host.current:
            try:self.host.stop()
            except Exception as error:self.item.setdefault('cleanupErrors',[]).append(str(error))
        super().cleanup()

    def audit(self):
        terrain.mixed.Planning.audit(self)
        c.need(self.item.get('realStateConnectionQualified') and self.host.records and all(r['status']=='passed' for r in self.host.records),'Missing real observer qualification')
        c.need(not (self.java_dir/'terrain-error').exists(),'Terrain qualification failed')
        summary=c.load(self.java_dir/'terrain-summary.json')
        c.need(summary['minimum']>0 and summary['intercepts']>0 and any('SearchTaskAnalysis' in k for k in summary['calls']),'Terrain not used')
        c.base.verify_files(self.java_dir,self.item['runtimeInputs'])
        self.item['terrainSummary']=summary

    def execute(self):
        self.prepare();candidate=Path(self.context['stateCandidate'])
        with services.running([self.node,ROOT/'scripts/g5_state/server.mjs',candidate/'service.json',self.run/'map-service'],self.run/'map-service') as resource_service:
            for mode in ('Headless','Gui'):
                c.need(resource_service.poll() is None,'Resource service exited')
                self.operation_deadline=time.monotonic()+450
                result=self.case(mode.lower(),mode)
                c.need(result['status']=='passed',result.get('error','Real state case failed'))
                c.need(resource_service.poll() is None,'Resource service failed during browser lifecycle')
                # Deliberately reset incomplete HTTP clients; this must not stop
                # the production service after normal browser/gateway closure.
                for _ in range(3):
                    with socket.create_connection(('127.0.0.1',8080)) as client:
                        client.sendall(b'GET /state/runtime.json HTTP/1.1\r\nHost: localhost\r\n')
                        client.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('HH',1,0))
                time.sleep(.3)
                c.need(resource_service.poll() is None and services.request('http://127.0.0.1:8080/map/health')[0]==200,'Client reset killed map service')
        c.need(self.inputs()==self.record['inputs'],'T05 sources changed')
        self.record.update(status='passed',stageQualified=False,simulationDisplayQualified=False)

class Session(StateRun):
    def body(self,mode,fault,keep_gui):
        terrain.mixed.Planning.body(self,mode,'',False)
        snapshot=self.host.live();c.save(self.run/'session-ready.json',dict(runId=self.args.run_id,backendRunId=snapshot['run_id'],url='http://127.0.0.1:8080',mode=mode))
        print('G5_STATE_SESSION_READY='+self.args.run_id+' URL=http://127.0.0.1:8080',flush=True)
        expected={r['taskId']:r['entityId'] for r in self.scene['assignments']};complete={};cursor=0;latest=0;paused=False
        while not (self.run/'request-stop').exists():
            self.alive()
            for row in self.observer.rows[cursor:]:
                cursor+=1
                if row['type']=='afrl.cmasi.SessionStatus':latest=max(latest,int(row['timeMs']))
                if row['type']=='uxas.messages.task.TaskComplete':
                    node=ET.fromstring(base64.b64decode(row['xmlBase64']));task=node.findtext('TaskID')
                    c.need(task in expected and [n.text for n in node.findall('EntitiesInvolved/int64')]==[expected[task]],'Unexpected completion')
                    complete[task]=int(node.findtext('TimeTaskCompleted'))
            if not paused and len(complete)==3 and latest>=max(complete.values())+3000:
                (self.java_dir/'request-pause').touch();self.wait('session-paused',lambda:any(e['kind']=='paused' for e in self.amase.events(self.java_dir)))
                paused=True;c.save(self.run/'session-paused.json',dict(completions=complete,simulationTimeMs=str(latest)))
            if paused:self.operation_deadline=time.monotonic()+300
            time.sleep(.1)
        self.item['sessionReady']=True

    def audit(self):
        terrain.mixed.Planning.audit(self)
        c.need(self.item.get('sessionReady') and self.host.records and all(r['status']=='passed' for r in self.host.records),'Session did not close normally')
        c.need(not (self.java_dir/'terrain-error').exists(),'Terrain query invalid')
        c.base.verify_files(self.java_dir,self.item['runtimeInputs'])
        self.item.update(demonstrationOnly=True,simulationDisplayQualified=False)

    def execute(self):
        self.prepare();candidate=Path(self.context['stateCandidate'])
        with services.running([self.node,ROOT/'scripts/g5_state/server.mjs',candidate/'service.json',self.run/'map-service'],self.run/'map-service'):
            self.operation_deadline=time.monotonic()+2650
            result=self.case('session-'+self.args.mode.lower(),self.args.mode)
            c.need(result['status']=='passed',result.get('error','Session failed'))
        c.need(self.inputs()==self.record['inputs'],'Session sources changed');self.record.update(status='passed',stageQualified=False,demonstrationOnly=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);parser.add_argument('--session',action='store_true');parser.add_argument('--mode',choices=['Gui','Headless'],default='Gui');args=parser.parse_args()
    args.root=ROOT;args.verify=False;args.keep_gui=False
    task=(Session if args.session else StateRun)(args)
    try:task.execute();return 0
    except Exception as error:task.record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(task.record['traceback'],flush=True);return 1
    finally:c.save(task.run/'runtime-result.json',task.record)

if __name__=='__main__':sys.exit(main())
