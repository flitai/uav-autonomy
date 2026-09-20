"""Bind independently audited G4-T07 flights to the finalized identical binaries."""
import argparse
import ast
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import traceback


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--baseline-run-id',required=True)
    parser.add_argument('--environment-run-id',required=True)
    args=parser.parse_args(); root=args.root.resolve()
    spec=importlib.util.spec_from_file_location('qualification_environment',root/'scripts/g4_environment/manage.py')
    env=importlib.util.module_from_spec(spec); spec.loader.exec_module(env)
    load,sha,need,save=env.load,env.sha,env.require,env.save
    run_id='g4-t07-qualified-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output=root/'out/runs'/run_id; output.mkdir()
    record={'task':'G4-T07','runId':run_id,'status':'running','stageQualified':False}
    try:
        policy=load(root/'config/g4-baseline.json')
        record['provenance']=env.verify_handoff(root,args.baseline_run_id)
        environment=root/'out/runs'/args.environment_run_id
        smoke=load(environment/'result.json')
        need(smoke['status']==load(environment/'entry-result.json')['status']=='passed' and
             smoke['verifyOnly'] and smoke['provenance']==record['provenance'],'Current environment qualification differs')
        env.verify_files(root,smoke['inputs']); env.environment(root)
        capture_id='g4-t07-capture-20260920-025046-760714'
        audit_id='g4-t07-audit-20260920-032048-023253'
        parent=root/'out/runs'/capture_id; capture=load(parent/'result.json')
        audit_dir=root/'out/runs'/audit_id; audit=load(audit_dir/'result.json')
        need(capture['status']==audit['status']=='passed' and capture['inputsUnchanged'] and
             audit['parentRunId']==capture_id and audit['parentResultSHA256']==sha(parent/'result.json') and
             all(audit[k] for k in ('taskExecutionValidated','taskCompletionValidated','coverageValidated')),
             'Independent flight qualification incomplete')
        need({k:v.lower() for k,v in capture['artifacts'].items()}==record['provenance']['artifacts'] and
             capture['amaseBuildRunId']==policy['amaseRevision']['buildRunId'],
             'Formal binaries differ from independently audited flights')
        before=root/'out/build/g4-source-revisions/g4-t07/manage-before.py'
        revised_path='scripts/g4_environment/manage.py'
        for row in capture['inputs']:
            if row['path']==revised_path:
                need(sha(before)==row['sha256'].lower(),'Qualification source predecessor differs')
                old,new=(ast.parse(p.read_text(encoding='utf-8-sig')) for p in (before,root/revised_path))
                filtered=lambda tree:[ast.dump(n,include_attributes=False) for n in tree.body
                    if not (isinstance(n,ast.FunctionDef) and n.name in ('verify_handoff','verify_amase_revision'))]
                need(filtered(old)==filtered(new),'A runtime environment function changed after capture')
            else: env.verify_files(root,[row])
        env.verify_files(root,audit['auditSources'])
        need(len(capture['cases'])==len(audit['cases'])==4,'Required scene count differs')
        for case,proof in zip(capture['cases'],audit['cases'],strict=True):
            directory=parent/case['name']; audited=audit_dir/proof['name']
            need(case==load(directory/'case-result.json') and case['name']==proof['name'] and
                 case['status']==proof['status']=='passed' and case['normalExit'] and case['portsReleased'] and
                 sha(directory/'case-result.json')==proof['caseReceiptSHA256'],'Case receipt changed')
            env.verify_files(directory,case['evidence'])
            need(sha(audited/'execution.json')==proof['executionSHA256'] and
                 sha(audited/'statistics.json')==proof['statisticsSHA256'],'Independent proof changed')
        # These are isolated policy copies; formal files and historical evidence stay immutable.
        checks=[]
        mutations=[('wrong-parent-amase',('amaseRevision','parentAmaseSHA256'),'0'*64),
                   ('wrong-current-amase',('amaseRevision','amaseSHA256'),'0'*64),
                   ('wrong-current-gui',('amaseRevision','guiRunId'),'g1-t04-run-0'),
                   ('wrong-finalize',('amaseRevision','finalizeRunId'),'g1-t04-finalize-0'),
                   ('wrong-amase-metadata',('amaseRevision','buildInfoSHA256'),'0'*64),
                   ('wrong-uxas-parent',('amaseRevision','parentFormalUxas','buildRunId'),'g2-t05-build-0'),
                   ('wrong-uxas-current',('amaseRevision','formalUxas','publishRunId'),'g2-t07-publish-0'),
                   ('wrong-g3-handoff',('g3HandoffSHA256',),'0'*64)]
        for label,keys,value in mutations:
            bad=deepcopy(policy); target=bad
            for key in keys[:-1]:target=target[key]
            target[keys[-1]]=value
            try:env.verify_handoff(root,args.baseline_run_id,bad)
            except RuntimeError as error:checks.append({'name':label,'rejected':True,'error':str(error)})
            else:raise RuntimeError('Invalid lineage accepted: '+label)
        for label,key in [('missing-revision','amaseRevision'),('missing-wal-revision','uxasRevision')]:
            bad=deepcopy(policy); del bad[key]
            try:env.verify_handoff(root,args.baseline_run_id,bad)
            except RuntimeError as error:checks.append({'name':label,'rejected':True,'error':str(error)})
            else:raise RuntimeError('Missing lineage accepted: '+label)
        paths=[Path(__file__).resolve(),root/revised_path,root/'config/g4-baseline.json',root/'config/g3-baseline.json']
        evidence=[parent/'result.json',audit_dir/'result.json',environment/'result.json',environment/'entry-result.json']
        record.update(status='passed',stageQualified=True,captureRunId=capture_id,auditRunId=audit_id,
            inputs=[{'path':p.relative_to(root).as_posix(),'sha256':sha(p)} for p in paths],
            receipts=[{'path':p.relative_to(root).as_posix(),'sha256':sha(p)} for p in evidence],
            qualificationSourceRevision={'path':revised_path,'beforePath':before.relative_to(root).as_posix(),
                'beforeSHA256':sha(before),'afterSHA256':sha(root/revised_path),
                'unchangedRuntimeFunctions':True,'reason':'Explicit AMASE finalization and UxAS handoff lineage'},
            artifactBytesIdentical=True,flightEvidenceReused=True,newFlightClaimed=False,
            taskExecutionValidated=True,taskCompletionValidated=True,coverageValidated=True,
            lineageRejections=checks,cases=audit['cases'])
        return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc()); return 1
    finally:
        save(output/'result.json',record)
        print('G4_T07_QUALIFICATION='+run_id,flush=True)
        if record['status']=='failed':print(record['traceback'],flush=True)


if __name__=='__main__':sys.exit(main())
