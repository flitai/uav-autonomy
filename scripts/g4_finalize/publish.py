"""Bind current visual acceptance to a passed same-package complete controlled run."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path
import shutil
import sys
import traceback


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
receipts=module('final_publish_receipts',Path(__file__).with_name('receipts.py'))
package=receipts.package
load,save,sha,need=package.load,package.save,package.sha,package.need


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--controlled-run',required=True); args=parser.parse_args(); root=args.root.resolve()
    directory=(root/'out/runs'/args.controlled_run).resolve(); need(directory.parent==root/'out/runs','Controlled path escapes')
    identity='g4-t09-publish-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'); output=root/'out/runs'/identity; output.mkdir()
    record=dict(task='G4-T09',runId=identity,status='running',stageQualified=False)
    pointer=root/'out/artifacts/gis-gateway/current.json'; old=pointer.read_bytes() if pointer.exists() else None; switched=False
    try:
        controlled=load(directory/'result.json')
        need(controlled['status']=='passed' and controlled['inputsUnchanged'] and
             controlled['scope']=='same-version-controlled-finalization' and controlled['manualGuiAcceptance'] is False,
             'Complete controlled run required; no substituted human inspection')
        package.verify_files(root,controlled['inputs'])
        confirmation=root/controlled['visualConfirmationPath']
        need(sha(confirmation)==controlled['visualConfirmationSHA256'] and load(confirmation)==controlled['visualConfirmation'],'Visual binding changed')
        record['visualReview']=receipts.visual(root,load(confirmation)); policy=record['visualReview']['policy']
        bundle=root/controlled['candidate']; digest=policy['packageSHA256']; manifest=package.verify(bundle,root,digest)
        need(controlled['packageSHA256']==digest and len(controlled['cases'])==1,'Controlled package/cases differ')
        validator=module('final_original_validation',root/'scripts/g4_stage/publish.py')
        original,original_result=validator.validate_run(root,policy['originalRunId'],bundle,digest,'Original')
        need(original_result['artifacts']==controlled['artifacts'],'Backend bytes differ between final cases')
        case=controlled['cases'][0]; folder=directory/case['name']
        need(case['mode']=='Gui' and case['controlledRevalidation'] and case['status']=='passed' and case['normalExit'] and
             case['portsReleased'] and not case.get('cleanupErrors') and load(folder/'case-result.json')==case,'Controlled normal exit incomplete')
        need(case['manualGuiAcceptance'] is False and case['visualConfirmationSHA256']==sha(confirmation),'Controlled visual claim differs')
        for path in (folder/'gateway-host').glob('instance-*/package-launch.json'):
            launch=load(path); need(launch['packageSHA256']==digest and Path(launch['bundle'])==bundle,'Controlled loaded package differs')
            for row in launch['loaded']:
                actual=Path(row['path']); need(actual.is_relative_to(bundle/'src') and sha(actual)==row['sha256'],'Loaded module changed')
        audit=module('final_controlled_audit',root/'scripts/g4_scale/audit.py')
        execution=module('final_controlled_execution',root/'scripts/g4_mixed/execution.py')
        coverage=module('final_controlled_coverage',root/'scripts/g4_scale/coverage.py')
        record['mixedAudit']=audit.case_audit(root,folder,output/'mixed-proof',execution,coverage)
        need(load(folder/'review/execution.json')==load(output/'mixed-proof/execution.json') and
             load(folder/'review/statistics.json')==load(output/'mixed-proof/statistics.json'),'Controlled post-close proof differs from its review')
        record['stability']=package.predecessor(root)
        record['finalRuns']=[dict(runId=r,resultSHA256=sha(p/'result.json')) for r,p in
                             [(policy['originalRunId'],original),(args.controlled_run,directory)]]
        record['manualGuiAcceptance']=load(confirmation)
        record['visualConfirmationPath']=confirmation.relative_to(root).as_posix(); record['visualConfirmationSHA256']=sha(confirmation)
        target=root/'out/artifacts/gis-gateway'/manifest['buildRunId']/identity/'package'
        shutil.copytree(bundle,target); package.verify(target,root,digest)
        source=[p for d in ('scripts/g4_stage','scripts/g4_finalize') for p in (root/d).glob('*.py')]+[root/'config/g4-finalization.json']
        record.update(status='passed',stageQualified=True,packageSHA256=digest,packagePath=target.relative_to(root).as_posix(),
            taskExecutionValidated=True,taskCompletionValidated=True,coverageValidated=True,stabilityValidated=True,
            normalExitValidated=True,artifacts=controlled['artifacts'],inputs=package.files(root,source),
            qualificationMethod='current visual acceptance plus same-byte full controlled GUI rerun; original failure retained')
        save(output/'qualification.json',record)
        new=dict(schemaVersion=1,buildRunId=manifest['buildRunId'],publicationRunId=identity,path=record['packagePath'],
                 packageSHA256=digest,qualificationSHA256=sha(output/'qualification.json'))
        if old is not None: (output/'previous-pointer.json').write_bytes(old)
        save(pointer,new); switched=True; need(load(pointer)==new,'Published pointer differs')
        record['pointer']=new; save(output/'result.json',record); print('G4_T09_PUBLISHED='+identity,flush=True); return 0
    except Exception as error:
        if switched:
            if old is None: pointer.unlink()
            else:
                temporary=pointer.with_suffix('.rollback'); temporary.write_bytes(old); temporary.replace(pointer)
        record.update(status='failed',stageQualified=False,error=str(error),traceback=traceback.format_exc())
        save(output/'result.json',record); print(record['traceback'],flush=True); return 1


if __name__=='__main__': sys.exit(main())
