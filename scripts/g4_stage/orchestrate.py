"""Sequential final stage; publication follows fresh GUI confirmation and audits."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path
import subprocess
import sys
import traceback


spec=importlib.util.spec_from_file_location('orchestrate_package',Path(__file__).with_name('package.py'))
package=importlib.util.module_from_spec(spec); spec.loader.exec_module(package)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--java-home',type=Path,required=True); parser.add_argument('--baseline-run-id',required=True)
    args=parser.parse_args(); root=args.root.resolve()
    identity='g4-t09-stage-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output=root/'out/runs'/identity; output.mkdir()
    record={'task':'G4-T09','runId':identity,'status':'running','children':[]}
    def invoke(label,command):
        print('G4_T09_START='+label,flush=True)
        with (output/(label+'.stdout')).open('wb') as stdout,(output/(label+'.stderr')).open('wb') as stderr:
            return subprocess.call(command,cwd=output,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        bundle=package.build(root,args.baseline_run_id)
        record.update(candidate=bundle.relative_to(root).as_posix(),packageSHA256=package.sha(bundle/'package.json'))
        package.save(output/'result.json',record)
        for scene,suffix in [('Original','original'),('Mixed20','mixed')]:
            child=identity.replace('-stage-','-'+suffix+'-'); record['children'].append(child)
            package.save(output/'result.json',record)
            command=[sys.executable,'-I','-B','-X','utf8',str(Path(__file__).with_name('runtime.py')),
                '--root',str(root),'--java-home',str(args.java_home.resolve()),'--baseline-run-id',args.baseline_run_id,
                '--bundle',str(bundle),'--scene',scene,'--run-id',child]
            result=invoke(scene,command)
            package.need(result==0 and package.load(root/'out/runs'/child/'result.json')['status']=='passed','Final child failed: '+child)
        result=invoke('Publish',[sys.executable,'-I','-B','-X','utf8',str(Path(__file__).with_name('publish.py')),
            '--root',str(root),'--bundle',str(bundle),'--original-run',record['children'][0],'--mixed-run',record['children'][1]])
        package.need(result==0,'Stage publication failed')
        record.update(status='passed',publication=package.load(root/'out/artifacts/gis-gateway/current.json')); return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc()); print(record['traceback'],flush=True); return 1
    finally:
        package.save(output/'result.json',record); print('G4_T09_STAGE='+identity+' STATUS='+record['status'],flush=True)


if __name__=='__main__': sys.exit(main())
