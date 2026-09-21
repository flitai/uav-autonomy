"""Real T04/G4 mission display, previous entity regression, isolated region wire checks."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('g5_missions_runtime_common',Path(__file__).with_name('common.py'));c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
entities=c.module('g5_missions_entity_runtime',ROOT/'scripts/g5_entities/runtime.py');state=entities.state

class MissionRun(entities.EntityRun):
    def inputs(self):return c.sources()
    def prepare(self):
        super().prepare();self.record.update(task='G5-T07',scope='routes-tasks-zones',missionDisplayQualified=False)
    def body(self,mode,fault,keep_gui):
        if self.entity_regression:return super().body(mode,fault,keep_gui)
        self.browser_dir=self.directory/'browser'
        with (self.directory/'browser.stdout').open('wb') as stdout,(self.directory/'browser.stderr').open('wb') as stderr:
            self.browser=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',str(ROOT/'tests/g5_missions/browser.py'),'--output',str(self.browser_dir),'--url','http://127.0.0.1:8080'],cwd=self.directory,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('mission-browser-before-backend',lambda:(self.browser_dir/'opened').exists() or self.browser.poll() is not None,55)
        c.need(self.browser.poll() is None,'Mission browser failed before backend')
        state.terrain.mixed.Planning.body(self,mode,'',False);self.host.live()
        self.wait('mission-real-completion-display',lambda:(self.browser_dir/'request-pause').exists() or self.browser.poll() is not None,230)
        c.need(self.browser.poll() is None,'Mission browser failed before completion comparison')
        (self.java_dir/'request-pause').touch();self.wait('mission-paused',lambda:any(r['kind']=='paused' for r in self.amase.events(self.java_dir)))
        (self.java_dir/'request-analysis').touch();self.wait('mission-analysis',lambda:(self.java_dir/'analysis-done').exists(),60)
        self.wait('mission-browser-verified',lambda:(self.browser_dir/'verified').exists() or self.browser.poll() is not None,70)
        c.need(self.browser.poll() is None,'Mission browser failed while paused')
        self.item['snapshot']=self.host.live();self.host.stop();(self.browser_dir/'gateway-stopped').touch()
        self.wait('mission-browser-exit',lambda:self.browser.poll() is not None,60)
        c.need(self.browser.returncode==0,'Mission browser failed')
        browser=c.load(self.browser_dir/'result.json');c.need(browser['status']=='passed','Mission browser result failed')
        self.item.update(browser=browser,realStateConnectionQualified=True,missionDisplayQualified=True)
    def execute(self):
        self.prepare();candidate=Path(self.context['stateCandidate']);service=c.load(candidate/'service.json')
        output=self.run/'map-service'
        with state.services.running([self.node,ROOT/'scripts/g5_state/server.mjs',candidate/'service.json',output],output) as process:
            for name,mode,regression in [('entities-headless','Headless',True),('entities-gui','Gui',True),('missions-headless','Headless',False),('missions-gui','Gui',False)]:
                c.need(process.poll() is None,'Resource service exited');self.entity_regression=regression;self.operation_deadline=time.monotonic()+450
                item=self.case(name,mode);c.need(item['status']=='passed',item.get('error','Mission case failed'))
            fixture=self.run/'independent-gateway';browser=self.run/'independent/browser'
            with state.services.running([self.web_python,'-I','-B','-X','utf8',ROOT/'tests/g5_missions/fixture_server.py',fixture],fixture):
                browser.parent.mkdir()
                c.invoke([self.web_python,'-I','-B','-X','utf8',ROOT/'tests/g5_missions/browser.py','--url','http://127.0.0.1:8080','--output',browser,'--fixture-server',fixture],self.run,'independent-regions',timeout=240)
                independent=c.load(browser/'result.json');c.need(independent['status']=='passed' and independent['exitCode']==0 and not independent['forcedTermination'],'Independent region rendering failed')
            checks=state.services.http_checks(service)
            conflict=self.run/'port-conflict';conflict.mkdir()
            c.invoke([self.node,ROOT/'scripts/g5_state/server.mjs',candidate/'service.json',conflict],self.run,'port-conflict',expected=1)
            c.need('EADDRINUSE' in (self.run/'port-conflict.stderr').read_text(),'Wrong port rejection')
            offline=self.run/'map-offline'
            c.invoke([self.web_python,'-I','-B','-X','utf8',ROOT/'tests/g5_map/map_browser.py','--url','http://127.0.0.1:8080','--output',offline],self.run,'map-offline',timeout=240)
            result=c.load(offline/'result.json');c.need(result['status']=='passed' and result['exitCode']==0 and not result['forcedTermination'],'Map regression failed')
            c.need(process.poll() is None,'Resource service failed')
        c.need(self.inputs()==self.record['inputs'],'T07 sources changed')
        self.record.update(status='passed',missionDisplayQualified=True,entityDisplayQualified=True,stageQualified=False,independentRegions=independent,resourceChecks=dict(http=checks,offlineMap=result,portConflictRejected=True))

class MissionSession(state.Session):
    def inputs(self):return c.sources()
    def prepare(self):
        super().prepare();self.record.update(task='G5-T07',scope='mission-session')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);parser.add_argument('--session',action='store_true');parser.add_argument('--mode',choices=['Gui','Headless'],default='Gui');a=parser.parse_args();a.root=ROOT;a.verify=False;a.keep_gui=False
    task=(MissionSession if a.session else MissionRun)(a)
    try:task.execute();return 0
    except Exception as error:task.record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(task.record['traceback']);return 1
    finally:c.save(task.run/'runtime-result.json',task.record)
if __name__=='__main__':sys.exit(main())
