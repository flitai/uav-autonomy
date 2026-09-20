"""Resolve the qualified local gateway; launch it alone or with a backend session."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path
import subprocess
import sys


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
package=module('entry_package',Path(__file__).with_name('package.py'))


def resolve(root):
    pointer=package.load(root/'out/artifacts/gis-gateway/current.json')
    bundle=(root/pointer['path']).resolve()
    package.need(bundle.is_relative_to(root/'out/artifacts/gis-gateway'),'Package path escapes')
    qualification=root/'out/runs'/pointer['publicationRunId']/'qualification.json'
    package.need(package.sha(qualification)==pointer['qualificationSHA256'],'Qualification changed')
    receipt=package.load(qualification)
    package.need(receipt['status']=='passed' and receipt['stageQualified'] and receipt['packageSHA256']==pointer['packageSHA256'],
                 'Gateway publication is not qualified')
    package.verify_files(root,receipt['inputs'])
    manifest=package.verify(bundle,root,pointer['packageSHA256'])
    environment=module('entry_environment',root/'scripts/g4_environment/manage.py')
    python,_=environment.environment(root)
    package.need(python==Path(manifest['pythonExecutable']),'Environment changed')
    return bundle,pointer,python


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    sub=parser.add_subparsers(dest='action',required=True)
    observer=sub.add_parser('observe'); observer.add_argument('--manifest',type=Path,required=True)
    observer.add_argument('--manifest-sha256',required=True); observer.add_argument('--output',type=Path,required=True)
    session=sub.add_parser('session'); session.add_argument('--baseline-run-id',required=True); session.add_argument('--java-home',type=Path,required=True)
    session.add_argument('--scene',choices=['Original','Mixed20'],default='Mixed20'); session.add_argument('--mode',choices=['Headless','Gui'],default='Gui')
    args=parser.parse_args(); root=args.root.resolve(); bundle,pointer,python=resolve(root)
    if args.action=='observe':
        command=[str(bundle/'scripts/g4_stage/launch.py'),'--root',str(root),'--manifest',str(args.manifest.resolve()),
            '--manifest-sha256',args.manifest_sha256,'--output',str(args.output.resolve()),'--package-sha256',pointer['packageSHA256']]
    else:
        identity='g4-t09-demo-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        command=[str(root/'scripts/g4_stage/session.py'),'--root',str(root),'--bundle',str(bundle),'--run-id',identity,
            '--java-home',str(args.java_home.resolve()),'--baseline-run-id',args.baseline_run_id,'--scene',args.scene,
            '--mode',args.mode]
        print('G4_SESSION_RUN_ID='+identity,flush=True)
    return subprocess.call([str(python),'-I','-B','-X','utf8',*command],cwd=root)


if __name__=='__main__': sys.exit(main())
