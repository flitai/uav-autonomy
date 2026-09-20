"""Accept only an explicit fresh user confirmation for the live reviewed GUI."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
package=module('finish_package',Path(__file__).with_name('package.py'))


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--run-id',required=True); parser.add_argument('--confirmation-text',required=True); args=parser.parse_args()
    root=args.root.resolve(); run=(root/'out/runs'/args.run_id).resolve()
    package.need(run.parent==root/'out/runs' and args.run_id.startswith('g4-t09-'),'Invalid run')
    ready,result=package.load(run/'gui-ready.json'),package.load(run/'result.json')
    package.need(result['task']=='G4-T09' and result['status']=='awaiting-gui' and ready['runId']==args.run_id,'No current review')
    review=run/ready['reviewPath']; package.need(package.sha(review)==ready['reviewSHA256'],'Review changed')
    package.verify_files(review.parent,package.load(review)['files'])
    sys.path.insert(0,str(root/'src'))
    from sim_bridge.windows import process_identity
    for identity in ready['processes']:
        package.need(process_identity(int(identity['pid']))==identity,'Reviewed process identity changed')
    request=dict(runId=args.run_id,nonce=ready['nonce'],controllerPid=ready['controllerPid'],javaPid=ready['javaPid'],uxasPid=ready['uxasPid'],
        readySHA256=package.sha(run/'gui-ready.json'),reviewSHA256=package.sha(review),manualGuiAcceptance=True,
        confirmationSource='user',confirmationText=args.confirmation_text,requestedAtEpochSeconds=time.time())
    receipts=module('finish_confirmation',root/'scripts/g3_acceptance/receipts.py')
    receipts.validate_confirmation(ready,request,request['readySHA256'],request['reviewSHA256'])
    with (run/'request-gui-acceptance.json').open('x',encoding='utf-8') as stream: json.dump(request,stream,ensure_ascii=False,indent=2)
    print('Current GUI confirmation recorded; the owner will close its processes normally.')
    return 0


if __name__=='__main__': sys.exit(main())
