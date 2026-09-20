"""Package isolation and premature/stale stage qualification refusals."""
import argparse
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--baseline-run-id',required=True)
    args=parser.parse_args(); root=args.root.resolve()
    package=module('checks_package',root/'scripts/g4_stage/package.py')
    directory=root/'out/runs'/('g4-t09-checks-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')); directory.mkdir()
    candidate=package.build(root,args.baseline_run_id); digest=package.sha(candidate/'package.json')
    manifest=package.verify(candidate,root,digest); checks=[]
    def rejected(name,call):
        try: call()
        except (RuntimeError,FileNotFoundError,KeyError) as error: checks.append({'name':name,'status':'passed','rejection':str(error)})
        else: raise AssertionError('Unexpected acceptance: '+name)
    checks.append({'name':'real-qualified-candidate','status':'passed','packageSHA256':digest})
    copy=directory/'中文 空格 bundle'; shutil.copytree(candidate,copy); package.verify(copy,root,digest)
    checks.append({'name':'relocated-Chinese-package','status':'passed'})
    rejected('manifest-digest',lambda:package.verify(copy,root,'0'*64))
    source=copy/'src/sim_bridge/gateway.py'; original=source.read_bytes(); source.write_bytes(original+b'\n')
    rejected('changed-core',lambda:package.verify(copy,root,digest)); source.write_bytes(original)
    extra=copy/'unknown.py'; extra.write_text(''); rejected('unexpected-package-file',lambda:package.verify(copy,root,digest)); extra.unlink()
    bad=deepcopy(manifest); bad['workspaceFiles'][0]['sha256']='0'*64; package.save(copy/'package.json',bad)
    rejected('changed-workspace-dependency',lambda:package.verify(copy,root))
    package.save(copy/'package.json',manifest)
    # Execute the copied launcher: hash refusal must precede any listener or output creation.
    output=directory/'refused-launch'/'observer'
    process=subprocess.run([manifest['pythonExecutable'],'-I','-B','-X','utf8',str(copy/'scripts/g4_stage/launch.py'),
        '--root',str(root),'--manifest',str(directory/'absent.json'),'--manifest-sha256','0'*64,
        '--package-sha256','0'*64,'--output',str(output)],capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode!=0 and b'Untrusted package manifest' in process.stderr and not output.parent.exists()
    checks.append({'name':'native-launch-refuses-before-side-effects','status':'passed'})
    receipts=module('checks_confirmation',root/'scripts/g3_acceptance/receipts.py')
    ready=dict(runId='current',nonce='nonce',controllerPid=10,javaPid=11,uxasPid=12,reviewSHA256='review',readyAtEpochSeconds=time.time())
    request=dict(runId='current',nonce='nonce',controllerPid=10,javaPid=11,uxasPid=12,reviewSHA256='review',readySHA256='ready',
        manualGuiAcceptance=True,confirmationSource='user',confirmationText='test fixture only',requestedAtEpochSeconds=time.time())
    assert receipts.validate_confirmation(ready,request,'ready','review')
    for key,value in [('runId','old'),('nonce','old'),('controllerPid',9),('reviewSHA256','old'),('readySHA256','old'),
                      ('manualGuiAcceptance',False),('confirmationSource','automatic'),('confirmationText',''),('requestedAtEpochSeconds',0)]:
        invalid={**request,key:value}; rejected('confirmation-'+key,lambda invalid=invalid:receipts.validate_confirmation(ready,invalid,'ready','review'))
    publisher=module('checks_publisher',root/'scripts/g4_stage/publish.py')
    fixture=directory/'not-final'; fixture.mkdir(); package.save(fixture/'result.json',{'status':'awaiting-gui'})
    rejected('premature-publication',lambda:publisher.validate_run(root,directory.name+'/not-final',candidate,digest,'Mixed20'))
    record={'status':'passed','checks':checks,'candidate':str(candidate.relative_to(root)),
            'sources':package.files(root,[Path(__file__),*sorted((root/'scripts/g4_stage').glob('*.py'))])}
    package.save(directory/'result.json',record); print(directory.name+' passed '+str(len(checks))); return 0


if __name__=='__main__': sys.exit(main())
