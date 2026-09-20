"""Complete same-byte GUI rerun after an explicitly bound visual confirmation."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
import traceback


ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
receipts=module('controlled_receipts',Path(__file__).with_name('receipts.py'))
stage=module('controlled_stage',ROOT/'scripts/g4_stage/runtime.py')
save,load,sha,need=receipts.save,receipts.load,receipts.sha,receipts.need


class Controlled(stage.Twenty):
    def inputs(self):
        files=[p for p in (self.root/'scripts/g4_finalize').glob('*.py')]+[self.root/'config/g4-finalization.json']
        return super().inputs()+stage.package.files(self.root,files)

    def prepare(self):
        super().prepare()
        acceptance=load(self.args.visual_confirmation)
        self.record['visualReference']=receipts.visual(self.root,acceptance)
        need(acceptance['packageSHA256']==self.package_sha,'Controlled package differs from the visually confirmed package')
        self.record.update(scope='same-version-controlled-finalization',diagnostic=False,manualGuiAcceptance=False,
            visualConfirmation=acceptance,visualConfirmationSHA256=sha(self.args.visual_confirmation),
            visualConfirmationPath=self.args.visual_confirmation.relative_to(self.root).as_posix())
        save(self.run/'result.json',self.record)

    def body(self,mode,fault,keep_gui):
        stage.scale.Scale.body(self,mode,fault,False)
        need(len(self.item['observedCompletions'])==20,'Controlled task set incomplete')
        self.wait('controlled-paused-session',lambda:any(r['type']=='afrl.cmasi.SessionStatus' and r['state']==2 for r in self.monitor.rows))
        self.review_time=[r['timeMs'] for r in self.monitor.rows if r['type']=='afrl.cmasi.SessionStatus'][-1]
        self.monitor.rows.clear(); save(self.directory/'preclose-case.json',self.item)
        with (self.directory/'review.stdout').open('wb') as stdout,(self.directory/'review.stderr').open('wb') as stderr:
            process=subprocess.Popen([sys.executable,'-I','-B','-X','utf8',str(self.root/'scripts/g4_stage/review.py'),
                '--root',str(self.root),'--directory',str(self.directory)],stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.wait('controlled-full-review',lambda:process.poll() is not None,600)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(); need(False,'Independent review required forced termination')
        need(process.returncode==0 and load(self.directory/'review/review.json')['status']=='passed','Controlled independent review failed')
        self.alive()  # Reviewed pause must remain intact right through normal close.
        self.item.update(controlledRevalidation=True,manualGuiAcceptance=False,
            visualConfirmationSHA256=self.record['visualConfirmationSHA256'],reviewSHA256=sha(self.directory/'review/review.json'))

    def audit(self):
        stage.scale.mixed.Capture.audit(self)
        need(len(self.item['observedCompletions'])==20 and len(self.host.records)==3,'Controlled full evidence incomplete')
        need(self.item['controlledRevalidation'] and not self.item['manualGuiAcceptance'],'Do not claim a new human inspection')


def main():
    parser=argparse.ArgumentParser()
    for name in ('root','bundle','java-home','visual-confirmation'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--baseline-run-id',required=True); args=parser.parse_args()
    args.root=args.root.resolve(); args.bundle=args.bundle.resolve(); args.visual_confirmation=args.visual_confirmation.resolve()
    args.run_id='g4-t09-controlled-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    args.mode='Gui'; args.seconds=785; args.purpose='Qualification'; args.keep_gui=False; args.verify=True
    directory=args.root/'out/runs'/args.run_id; directory.mkdir()
    save(directory/'context.json',dict(baselineRunId=args.baseline_run_id,javaHome=str(args.java_home.resolve()),
                                     configuration=str(args.root/'config/g3-startup.json')))
    task=Controlled(args)
    try: task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed',error=str(error),traceback=traceback.format_exc()); print(task.record['traceback'],flush=True); return 1
    finally:
        save(directory/'result.json',task.record); print('G4_T09_CONTROLLED='+args.run_id+' STATUS='+task.record['status'],flush=True)


if __name__=='__main__': sys.exit(main())
