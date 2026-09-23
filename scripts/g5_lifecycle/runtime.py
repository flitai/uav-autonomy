"""G5-T08 real terrain browser, observer and gateway recovery matrix."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

coverage=module('g5_lifecycle_coverage',ROOT/'scripts/g5_coverage/runtime.py')
c=coverage.c
state=coverage.state
proxy=module('g5_lifecycle_proxy',ROOT/'tests/g4_recovery/proxy.py')


class LifecycleRun(coverage.CoverageRun):
    def inputs(self):
        paths=[p for folder in ('scripts/g5_lifecycle','tests/g5_lifecycle') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        paths.append(ROOT/'tests/g4_recovery/proxy.py')
        paths.append(ROOT/'tests/windows/g5-lifecycle.tests.ps1')
        return c.sources()+c.base.inventory(ROOT,paths)

    def prepare(self):
        super().prepare()
        self.record.update(task='G5-T08',scope='real-browser-observer-lifecycle',lifecycleQualified=False)

    def files(self,mode,fault):
        self.proxies={};self.browser_command=0
        super().files(mode,fault)

    def handshake(self):
        # Preserve the T04 backend; only the gateway's two read-only observation
        # sockets pass through run-owned fault proxies.
        state.terrain.mixed.startup.Startup.handshake(self)
        ports={'amase':15555,'uxas':19999}
        for name,upstream in [('amase',self.ports['amasePort']),('uxas',self.ports['observerPort'])]:
            self.amase.check_port(ports[name]);self.proxies[name]=proxy.ObserverProxy(ports[name],upstream)
        self.host=state.stage.TwentyHost(self,self.web_python,self.schema,ports)
        self.host.start()
        self.collector=coverage.collector.Collector(self.directory/'gateway-host/manifest.json',self.prepared,self.run/'coverage/live.json')
        self.collector.start()

    def cleanup(self):
        try:
            if getattr(self,'browser',None) and self.browser.poll() is None:
                try:self.command('stop',15)
                except Exception:self.item.setdefault('cleanupErrors',[]).append('Browser normal-stop request failed')
            super().cleanup()
        finally:
            for value in self.proxies.values():value.close()
            self.item['observerProxies']={name:value.summary() for name,value in self.proxies.items()}
            for port in (15555,19999):self.amase.check_port(port)

    def status(self):
        path=self.browser_dir/'status.json'
        return c.load(path) if path.exists() else {}

    def command(self,action,seconds=30):
        number=self.browser_command;self.browser_command+=1
        path=self.browser_dir/'commands'/f'{number:03d}.json'
        path.parent.mkdir(exist_ok=True)
        c.save(path,{'action':action})
        receipt=self.browser_dir/'responses'/f'{number:03d}.json'
        self.wait('browser-'+action+'-'+str(number),lambda:receipt.exists() or self.browser.poll() is not None,seconds)
        c.need(self.browser.poll() is None or action=='stop','Browser exited during '+action)
        c.need(receipt.exists() and c.load(receipt)['status']=='passed','Browser command failed: '+action)
        return number

    def browser_live(self,stream=None,seconds=50):
        def ready():
            c.need(self.browser.poll() is None,'Lifecycle browser exited during recovery')
            s=self.status();identity=s.get('identity') or {}
            return (s.get('phase')=='live' and identity.get('run_id')==self.host.manifest['run_id'] and
                    (stream is None or identity.get('stream_id')==stream) and
                    s.get('coverageRunId')==identity.get('run_id') and
                    s.get('entityObjects')==3 and s.get('currentObjects',0)>0 and
                    s.get('accumulatedObjects',0)>0)
        self.wait('browser-restored-complete',ready,seconds)
        return self.status()

    def browser_stale(self,seconds=25):
        def stale():
            c.need(self.browser.poll() is None,'Lifecycle browser exited during outage')
            s=self.status()
            return (s.get('phase') in ('recovering','degraded','waiting-snapshot','connecting')
                    and all(s.get(k)==0 for k in ('entityObjects','missionObjects','currentObjects','accumulatedObjects'))
                    and s.get('coverageRunId') is None and '已过期' in s.get('timeText',''))
        self.wait('browser-cleared-on-gap',stale,seconds)
        first=self.status();time.sleep(1.2);second=self.status()
        c.need(first.get('lastKnownTime')==second.get('lastKnownTime'),'Stale simulation time moved')
        return second

    def outage(self,name,channels):
        before=self.host.live()
        for channel in channels:self.proxies[channel].cut()
        self.host.wait(lambda:not self.host.health()['ready'],name+' gateway suspended')
        c.need(self.host.request('/api/v1/snapshot')[0]==503,'Incomplete gateway snapshot was published')
        stale=self.browser_stale()
        for channel in channels:self.proxies[channel].restore()
        after=self.host.live()
        c.need(after['run_id']==before['run_id'] and after['stream_id']!=before['stream_id'],'Recovery identity incorrect')
        fresh=self.browser_live(after['stream_id'])
        self.item.setdefault('recovery',[]).append(dict(name=name,oldStream=before['stream_id'],newStream=after['stream_id'],
                  stale=stale,fresh=fresh))

    def body(self,mode,fault,keep_gui):
        self.browser_dir=self.directory/'browser'
        with (self.directory/'browser.stdout').open('wb') as stdout,(self.directory/'browser.stderr').open('wb') as stderr:
            self.browser=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',str(ROOT/'tests/g5_lifecycle/browser.py'),
                '--output',str(self.browser_dir),'--url','http://127.0.0.1:8080'],cwd=self.directory,stdout=stdout,stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('browser-opened-before-backend',lambda:(self.browser_dir/'opened').exists() or self.browser.poll() is not None,55)
        c.need(self.browser.poll() is None,'Lifecycle browser failed at startup')
        state.terrain.mixed.Planning.body(self,mode,'',False)
        first=self.host.live();self.browser_live(first['stream_id'],75)
        self.outage('amase-observer',['amase'])
        self.outage('uxas-observer',['uxas'])
        self.outage('both-observers',['amase','uxas'])
        before=self.host.live();self.host.stop()
        self.browser_stale()
        self.host.start();after=self.host.live()
        c.need(after['run_id']==before['run_id'] and after['stream_id']!=before['stream_id'],'Gateway restart identity incorrect')
        self.item.setdefault('recovery',[]).append(dict(name='gateway-restart',oldStream=before['stream_id'],
                  newStream=after['stream_id'],fresh=self.browser_live(after['stream_id'])))
        joined=self.command('late-join',70)
        late=c.load(self.browser_dir/f'late-{joined:03d}.json')
        c.need(late['identity']['run_id']==after['run_id'] and late['identity']['stream_id']==after['stream_id'],
               'Late browser joined the wrong run or stream')
        old_origin=self.status()['pageOrigin'];self.command('refresh',20)
        self.wait('browser-refresh-new-snapshot',lambda:self.status().get('pageOrigin')!=old_origin and
                  self.status().get('snapshots',0)>=1 and self.status().get('phase')=='live',65)
        self.browser_live(after['stream_id'])
        c.invoke([self.web_python,'-I','-B','-X','utf8',ROOT/'tests/g5_lifecycle/slow.py',
                  self.directory/'slow-client.json'],self.run,'slow-client',timeout=25)
        c.need(self.host.health()['ready'] and self.status()['phase']=='live','Slow client affected normal viewer or gateway')
        expected={r['taskId']:r['entityId'] for r in self.scene['assignments']}
        completed={};cursor=0;latest=0
        def terminal():
            nonlocal cursor,latest
            for row in self.observer.rows[cursor:]:
                cursor+=1
                if row['type']=='afrl.cmasi.SessionStatus':latest=max(latest,int(row['timeMs']))
                if row['type']=='uxas.messages.task.TaskComplete':
                    node=ET.fromstring(base64.b64decode(row['xmlBase64']))
                    task=node.findtext('TaskID');entities=[n.text for n in node.findall('EntitiesInvolved/int64')]
                    c.need(task in expected and entities==[expected[task]] and task not in completed,'Wrong or duplicate completion')
                    completed[task]=node.findtext('TimeTaskCompleted')
            return {'3001','3002'}.issubset(completed) and latest>=max(int(completed[k]) for k in ('3001','3002'))+3000
        self.wait('real-point-area-completions',terminal,300)
        (self.java_dir/'request-pause').touch();self.wait('lifecycle-backend-paused',lambda:any(e['kind']=='paused' for e in self.amase.events(self.java_dir)))
        (self.java_dir/'request-analysis').touch();self.wait('native-analysis',lambda:(self.java_dir/'analysis-done').exists(),90)
        final=self.host.live()
        self.wait('browser-retained-completions',lambda:{'3001','3002'}.issubset(self.status().get('completed',[])),45)
        capture=self.command('capture')
        observed=c.load(self.browser_dir/f'capture-{capture:03d}.json')
        c.need(observed['business']['state']==final['state'],'Paused browser state differs from authoritative gateway snapshot')
        c.need(observed['coverage']['snapshot']['runId']==final['run_id'],'Coverage run identity differs')
        self.item.update(observedCompletions=completed,finalSnapshot=final,pausedBrowserCapture=observed,
                         realStateConnectionQualified=True,missionDisplayQualified=True,coverageDisplayQualified=True)
        self.command('imagery-failure',25)
        c.need(self.host.health()['ready'] and self.status()['phase']=='live','Online imagery failure affected backend')
        # The map resource process is independent from the simulation and
        # gateway. An owned service restart must produce a fresh browser
        # snapshot while preserving the backend run identity.
        (self.service_output/'request-stop').touch()
        self.wait('map-service-normal-stop',lambda:self.service_process.poll() is not None,25)
        c.need(self.service_process.returncode==0,'Map service did not exit normally')
        self.browser_stale()
        resumed=self.directory/'map-service-restarted'
        with state.services.running([self.node,ROOT/'scripts/g5_coverage/server.mjs',
                                     Path(self.context['stateCandidate'])/'service.json',resumed,
                                     self.run/'coverage/live.json'],resumed):
            self.browser_live(final['stream_id'],65)
            from afrl.cmasi.RemoveTasks import RemoveTasks
            from afrl.cmasi.RemoveEntities import RemoveEntities
            remove=RemoveTasks();remove.TaskList=[3001];self.send(remove,'remove-completed-task')
            remove=RemoveEntities();remove.EntityList=[500];self.send(remove,'remove-entity')
            def deleted():
                status,snapshot=self.host.request('/api/v1/snapshot')
                return snapshot if status==200 and '3001' not in snapshot['state']['tasks'] and '500' not in snapshot['state']['entities'] else None
            after_delete=self.wait('legitimate-deletion',deleted,35)
            self.wait('browser-deletion-and-cumulative-cleanup',lambda:'3001' not in (self.status().get('coverageTasks') or []) and
                      self.status().get('counts',{}).get('tasks')==2 and self.status().get('entityObjects')==2 and
                      all(not k.startswith('500:') for k in self.status().get('currentSensors',[])),45)
            deleted_capture=self.command('capture')
            deleted_view=c.load(self.browser_dir/f'capture-{deleted_capture:03d}.json')
            c.need(deleted_view['business']['state']==after_delete['state'],'Deleted objects differ from gateway snapshot')
            self.item['deletion']=dict(taskId='3001',entityId='500',gateway=after_delete,
                                       browser=deleted_view['summary'])
            self.command('stop');self.wait('browser-normal-exit',lambda:self.browser.poll() is not None,45)
            browser=c.load(self.browser_dir/'result.json')
            c.need(self.browser.returncode==0 and browser['status']=='passed' and not browser['forcedTermination'],'Browser did not close normally')
            self.item['browser']=browser
            self.alive();c.need(self.host.health()['ready'],'Browser lifecycle affected the backend')
        self.host.stop()
        self.item['lifecycleQualified']=True

    def execute(self):
        self.prepare();candidate=Path(self.context['stateCandidate'])
        for mode in ('Headless','Gui'):
            output=self.run/('map-service-'+mode.lower())
            with state.services.running([self.node,ROOT/'scripts/g5_coverage/server.mjs',candidate/'service.json',output,
                                         self.run/'coverage/live.json'],output) as service:
                self.service_process=service;self.service_output=output
                self.operation_deadline=time.monotonic()+2300
                item=self.case('lifecycle-'+mode.lower(),mode)
                c.need(item['status']=='passed' and item.get('lifecycleQualified'),item.get('error','Lifecycle case failed'))
        c.need(self.inputs()==self.record['inputs'],'Lifecycle sources changed')
        self.record.update(status='passed',lifecycleQualified=True,stageQualified=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True)
    args=parser.parse_args();args.root=ROOT;args.verify=False;args.keep_gui=False
    task=LifecycleRun(args)
    try:task.execute();return 0
    except Exception as error:
        task.record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(task.record['traceback'],flush=True);return 1
    finally:c.save(task.run/'runtime-result.json',task.record)

if __name__=='__main__':sys.exit(main())
