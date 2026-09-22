"""Run the qualified T07 simulation with optional, isolated coverage analysis."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('coverage_runtime_common',Path(__file__).with_name('common.py'));c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
missions=c.module('coverage_previous_runtime',ROOT/'scripts/g5_missions/runtime.py');state=missions.state
collector=c.module('coverage_collector',Path(__file__).with_name('collector.py'))

class WithCoverage:
    def inputs(self):return c.sources()
    def prepare(self):
        super().prepare();self.record.update(task='G5-Coverage',scope='current-and-accumulated-coverage',coverageDisplayQualified=False)
    def files(self,mode,fault):
        self.collector=None;super().files(mode,fault)
    def handshake(self):
        super().handshake()
        self.collector=collector.Collector(self.directory/'gateway-host/manifest.json',self.prepared,self.run/'coverage/live.json');self.collector.start()
    def cleanup(self):
        try:
            if self.collector:
                result=self.collector.stop();self.item['coverageCollector']=result;c.save(self.directory/'coverage-collector.json',result)
                if result['status']!='passed':self.item.setdefault('cleanupErrors',[]).append('Coverage worker failed: '+str(result['error']))
        finally:super().cleanup()
    def service(self):
        output=self.run/'map-service'
        return state.services.running([self.node,ROOT/'scripts/g5_coverage/server.mjs',Path(self.context['stateCandidate'])/'service.json',output,self.run/'coverage/live.json'],output)

class CoverageRun(WithCoverage,missions.MissionRun):
    def body(self,mode,fault,keep_gui):
        if self.entity_regression:return super().body(mode,fault,keep_gui)
        self.browser_dir=self.directory/'browser'
        with (self.directory/'browser.stdout').open('wb') as stdout,(self.directory/'browser.stderr').open('wb') as stderr:
            self.browser=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',str(ROOT/'tests/g5_coverage/browser.py'),'--output',str(self.browser_dir),'--url','http://127.0.0.1:8080'],cwd=self.directory,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('coverage-browser-open',lambda:(self.browser_dir/'opened').exists() or self.browser.poll() is not None,55);c.need(self.browser.poll() is None,'Coverage browser failed at startup')
        state.terrain.mixed.Planning.body(self,mode,'',False);self.host.live()
        self.wait('coverage-completion',lambda:(self.browser_dir/'request-pause').exists() or self.browser.poll() is not None,230);c.need(self.browser.poll() is None,'Coverage browser failed before completion')
        (self.java_dir/'request-pause').touch();self.wait('coverage-paused',lambda:any(r['kind']=='paused' for r in self.amase.events(self.java_dir)))
        (self.java_dir/'request-analysis').touch();self.wait('coverage-native-analysis',lambda:(self.java_dir/'analysis-done').exists(),60)
        self.wait('coverage-browser-verified',lambda:(self.browser_dir/'verified').exists() or self.browser.poll() is not None,90);c.need(self.browser.poll() is None,'Coverage browser failed while paused')
        self.item['snapshot']=self.host.live();self.host.stop();(self.browser_dir/'gateway-stopped').touch()
        self.wait('coverage-browser-exit',lambda:self.browser.poll() is not None,60);c.need(self.browser.returncode==0,'Coverage browser failed')
        browser=c.load(self.browser_dir/'result.json');c.need(browser['status']=='passed','Coverage browser receipt failed')
        self.item.update(browser=browser,realStateConnectionQualified=True,missionDisplayQualified=True,coverageDisplayQualified=True)
    def execute(self):
        self.prepare();candidate=Path(self.context['stateCandidate']);service=c.load(candidate/'service.json')
        with self.service() as process:
            for name,mode,regression in [('entities-headless','Headless',True),('entities-gui','Gui',True),('coverage-headless','Headless',False),('coverage-gui','Gui',False)]:
                c.need(process.poll() is None,'Coverage map service stopped');self.entity_regression=regression;self.operation_deadline=time.monotonic()+500
                item=self.case(name,mode);c.need(item['status']=='passed',item.get('error','Coverage real case failed'))
            checks=state.services.http_checks(service)
            conflict=self.run/'port-conflict';conflict.mkdir();c.invoke([self.node,ROOT/'scripts/g5_coverage/server.mjs',candidate/'service.json',conflict,self.run/'coverage/live.json'],self.run,'port-conflict',expected=1)
            c.need('EADDRINUSE' in (self.run/'port-conflict.stderr').read_text(),'Wrong port conflict error')
            offline=self.run/'map-offline';c.invoke([self.web_python,'-I','-B','-X','utf8',ROOT/'tests/g5_map/map_browser.py','--url','http://127.0.0.1:8080','--output',offline],self.run,'map-offline',timeout=240)
            result=c.load(offline/'result.json');c.need(result['status']=='passed' and result['exitCode']==0 and not result['forcedTermination'],'Map regression failed')
        c.need(self.inputs()==self.record['inputs'],'Coverage source changed');self.record.update(status='passed',coverageDisplayQualified=True,stageQualified=False,resourceChecks=dict(http=checks,offlineMap=result,portConflictRejected=True))

class CoverageSession(WithCoverage,state.Session):
    def execute(self):
        self.prepare()
        with self.service():
            self.operation_deadline=time.monotonic()+2650
            result=self.case('session-'+self.args.mode.lower(),self.args.mode);c.need(result['status']=='passed',result.get('error','Coverage session failed'))
        c.need(self.inputs()==self.record['inputs'],'Coverage source changed');self.record.update(status='passed',stageQualified=False,demonstrationOnly=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--session',action='store_true');p.add_argument('--mode',choices=['Gui','Headless'],default='Gui');a=p.parse_args();a.root=ROOT;a.verify=False;a.keep_gui=False
    task=(CoverageSession if a.session else CoverageRun)(a)
    try:task.execute();return 0
    except Exception as error:task.record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(task.record['traceback']);return 1
    finally:c.save(task.run/'runtime-result.json',task.record)
if __name__=='__main__':sys.exit(main())
