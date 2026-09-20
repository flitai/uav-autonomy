"""Post-close stage audit and atomic publication of the exact tested gateway."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path
import shutil
import sys
import traceback


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
package=module('publish_package',Path(__file__).with_name('package.py'))
load,save,sha,need=package.load,package.save,package.sha,package.need


def validate_run(root,identity,bundle,digest,scene):
    directory=(root/'out/runs'/identity).resolve(); need(directory.parent==root/'out/runs','Run path escapes')
    result=load(directory/'result.json')
    need(result['status']=='passed' and result['task']=='G4-T09' and result['inputsUnchanged'] and
         result['purpose']=='Qualification' and result['packageSHA256']==digest,'Unqualified final run')
    package.verify_files(root,result['inputs'])
    for case in result['cases']:
        need(case['status']=='passed' and case['normalExit'] and case['portsReleased'],'Final run did not close normally')
        need(load(directory/case['name']/'case-result.json')==case,'Case receipt changed')
        package.verify_files(directory/case['name'],case['evidence'])
        for path in (directory/case['name']/'gateway-host').glob('instance-*/package-launch.json'):
            launch=load(path); need(launch['packageSHA256']==digest and Path(launch['bundle'])==bundle,'Wrong loaded bundle')
            for source in launch['loaded']:
                actual=Path(source['path']); need(actual.is_relative_to(bundle/'src') and sha(actual)==source['sha256'],'Loaded source changed')
    if scene=='Original':
        need(len(result['cases'])==2 and {c['mode'] for c in result['cases']}=={'Headless','Gui'} and
             result['gatewayCompletionValidated'] and result['coverageValidated'],'Original matrix incomplete')
    else:
        need(len(result['cases'])==1 and result['cases'][0]['mode']=='Gui' and result.get('manualGuiAcceptance'),'Current GUI missing')
        ready=load(directory/'gui-ready.json'); confirmation=load(directory/'request-gui-acceptance.json')
        review=directory/ready['reviewPath']
        receipts=module('publish_confirmation',root/'scripts/g3_acceptance/receipts.py')
        receipts.validate_confirmation(ready,confirmation,sha(directory/'gui-ready.json'),sha(review))
        need(confirmation==result['manualGuiAcceptance']==result['cases'][0]['manualGuiAcceptance'],'Confirmation differs')
        package.verify_files(review.parent,load(review)['files'])
    return directory,result


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--original-run',required=True); parser.add_argument('--mixed-run',required=True); args=parser.parse_args()
    root=args.root.resolve(); bundle=args.bundle.resolve(); digest=sha(bundle/'package.json')
    identity='g4-t09-publish-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output=root/'out/runs'/identity; output.mkdir()
    record=dict(task='G4-T09',runId=identity,status='running',stageQualified=False,packageSHA256=digest)
    pointer=root/'out/artifacts/gis-gateway/current.json'; old=pointer.read_bytes() if pointer.exists() else None; switched=False
    try:
        manifest=package.verify(bundle,root,digest); record['stability']=package.predecessor(root)
        original,original_receipt=validate_run(root,args.original_run,bundle,digest,'Original')
        mixed,mixed_receipt=validate_run(root,args.mixed_run,bundle,digest,'Mixed20')
        need(original_receipt['artifacts']==mixed_receipt['artifacts'],'Final backend combination differs')
        audit=module('stage_final_audit',root/'scripts/g4_scale/audit.py')
        execution=module('stage_final_execution',root/'scripts/g4_mixed/execution.py')
        coverage=module('stage_final_coverage',root/'scripts/g4_scale/coverage.py')
        case=mixed_receipt['cases'][0]
        record['mixedAudit']=audit.case_audit(root,mixed/case['name'],output/'mixed-proof',execution,coverage)
        need(load(mixed/case['name']/'review/execution.json')==load(output/'mixed-proof/execution.json') and
             load(mixed/case['name']/'review/statistics.json')==load(output/'mixed-proof/statistics.json'),
             'Post-close proof differs from the reviewed GUI')
        record['finalRuns']=[dict(runId=identity,resultSHA256=sha(directory/'result.json')) for identity,directory in
                             [(args.original_run,original),(args.mixed_run,mixed)]]
        record['manualGuiAcceptance']=mixed_receipt['manualGuiAcceptance']
        target=root/'out/artifacts/gis-gateway'/manifest['buildRunId']/identity/'package'
        shutil.copytree(bundle,target); package.verify(target,root,digest)
        record.update(status='passed',stageQualified=True,taskExecutionValidated=True,taskCompletionValidated=True,
            coverageValidated=True,stabilityValidated=True,normalExitValidated=True,packagePath=target.relative_to(root).as_posix(),
            artifacts=mixed_receipt['artifacts'],inputs=package.files(root,[p for p in (root/'scripts/g4_stage').glob('*.py')]))
        save(output/'qualification.json',record)
        new=dict(schemaVersion=1,buildRunId=manifest['buildRunId'],publicationRunId=identity,path=record['packagePath'],
                 packageSHA256=digest,qualificationSHA256=sha(output/'qualification.json'))
        if old is not None: (output/'previous-pointer.json').write_bytes(old)
        save(pointer,new); switched=True
        need(load(pointer)==new,'Published pointer differs')
        record['pointer']=new; save(output/'result.json',record)
        print('G4_T09_PUBLISHED='+identity,flush=True); return 0
    except Exception as error:
        if switched:
            if old is None: pointer.unlink()
            else:
                temporary=pointer.with_suffix('.rollback'); temporary.write_bytes(old); temporary.replace(pointer)
        record.update(status='failed',stageQualified=False,error=str(error),traceback=traceback.format_exc())
        save(output/'result.json',record); print(record['traceback'],flush=True); return 1


if __name__=='__main__': sys.exit(main())
