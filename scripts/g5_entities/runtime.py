"""Real T04 terrain / formal G4 sessions observed by the T06 browser probe."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import traceback

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('g5_entities_runtime_common',Path(__file__).with_name('common.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
state=c.module('g5_entities_state_runtime',ROOT/'scripts/g5_state/runtime.py')

class EntityRun(state.StateRun):
    def inputs(self):return c.sources()
    def prepare(self):
        super().prepare();self.record.update(task='G5-T06',scope='entities-attitude-time',entityDisplayQualified=False)
    def body(self,mode,fault,keep_gui):
        self.browser_dir=self.directory/'browser'
        with (self.directory/'browser.stdout').open('wb') as stdout,(self.directory/'browser.stderr').open('wb') as stderr:
            self.browser=subprocess.Popen([str(self.web_python),'-I','-B','-X','utf8',str(ROOT/'tests/g5_entities/browser.py'),'--output',str(self.browser_dir),'--url','http://127.0.0.1:8080'],cwd=self.directory,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('entity-browser-before-backend',lambda:(self.browser_dir/'opened').exists() or self.browser.poll() is not None,45)
        c.need(self.browser.poll() is None,'Entity browser failed before backend')
        state.terrain.mixed.Planning.body(self,mode,'',False);self.host.live()
        self.wait('entity-browser-request-pause',lambda:(self.browser_dir/'request-pause').exists() or self.browser.poll() is not None,200)
        c.need(self.browser.poll() is None,'Entity browser failed before pose checks')
        (self.java_dir/'request-pause').touch();self.wait('entity-paused',lambda:any(r['kind']=='paused' for r in self.amase.events(self.java_dir)))
        (self.java_dir/'request-analysis').touch();self.wait('entity-analysis',lambda:(self.java_dir/'analysis-done').exists(),60)
        self.wait('entity-browser-stable',lambda:(self.browser_dir/'verified').exists() or self.browser.poll() is not None,100)
        c.need(self.browser.poll() is None,'Entity browser failed while paused')
        self.item['snapshot']=self.host.live();self.host.stop();(self.browser_dir/'gateway-stopped').touch()
        self.wait('entity-browser-exit',lambda:self.browser.poll() is not None,60)
        c.need(self.browser.returncode==0,'Entity browser failed')
        browser=c.load(self.browser_dir/'result.json');c.need(browser['status']=='passed','Entity browser result failed')
        self.item.update(browser=browser,realStateConnectionQualified=True,entityDisplayQualified=True)
    def execute(self):
        super().execute()
        candidate=Path(self.context['stateCandidate']);service=c.load(candidate/'service.json')
        output=self.run/'map-regression'
        with state.services.running([self.node,ROOT/'scripts/g5_state/server.mjs',candidate/'service.json',output],output) as process:
            checks=state.services.http_checks(service)
            conflict=self.run/'port-conflict';conflict.mkdir()
            c.invoke([self.node,ROOT/'scripts/g5_state/server.mjs',candidate/'service.json',conflict],self.run,'port-conflict',expected=1)
            c.need('EADDRINUSE' in (self.run/'port-conflict.stderr').read_text(),'Wrong port rejection')
            browser=self.run/'map-offline'
            c.invoke([self.web_python,'-I','-B','-X','utf8',ROOT/'tests/g5_map/map_browser.py','--url','http://127.0.0.1:8080','--output',browser],self.run,'map-offline',timeout=240)
            result=c.load(browser/'result.json');c.need(result['status']=='passed' and result['exitCode']==0 and not result['forcedTermination'],'Composed map regression failed')
            c.need(process.poll() is None,'Map service failed')
        self.record.update(entityDisplayQualified=True,resourceChecks=dict(http=checks,offlineMap=result,portConflictRejected=True))

class EntitySession(state.Session):
    def inputs(self):return c.sources()
    def prepare(self):
        super().prepare();self.record.update(task='G5-T06',scope='entity-session')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);parser.add_argument('--session',action='store_true');parser.add_argument('--mode',choices=['Gui','Headless'],default='Gui');a=parser.parse_args();a.root=ROOT;a.verify=False;a.keep_gui=False
    task=(EntitySession if a.session else EntityRun)(a)
    try:task.execute();return 0
    except Exception as error:task.record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(task.record['traceback']);return 1
    finally:c.save(task.run/'runtime-result.json',task.record)
if __name__=='__main__':sys.exit(main())
