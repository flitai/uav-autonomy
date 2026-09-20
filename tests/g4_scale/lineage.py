"""Reject unrelated scale packages and missing predecessor qualifications."""
import argparse
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline-run-id',required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    spec=importlib.util.spec_from_file_location('scale_source_checks',root/'scripts/g4_environment/manage.py')
    env=importlib.util.module_from_spec(spec);spec.loader.exec_module(env)
    policy=env.load(root/'config/g4-baseline.json');env.verify_handoff(root,args.baseline_run_id)
    checks=[]
    for name,keys,value in [
        ('wrong-parent',('uxasScaleRevision','parentFormalUxas','buildRunId'),'g2-t05-build-0'),
        ('wrong-current',('uxasScaleRevision','formalUxas','publishRunId'),'g2-t07-publish-0'),
        ('wrong-executable',('uxasScaleRevision','uxasSHA256'),'0'*64),
        ('wrong-source',('uxasScaleRevision','sources',0,'sha256'),'0'*64),
        ('wrong-receipt',('uxasScaleRevision','receipts',0,'sha256'),'0'*64),
        ('wrong-amase',('amaseRevision','buildInfoSHA256'),'0'*64)]:
        bad=deepcopy(policy);target=bad
        for key in keys[:-1]:target=target[key]
        target[keys[-1]]=value
        try:env.verify_handoff(root,args.baseline_run_id,bad)
        except RuntimeError as error:checks.append({'name':name,'error':str(error)})
        else:raise AssertionError('Invalid source accepted: '+name)
    output=root/'out/runs'/('g4-t08-lineage-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir()
    result={'status':'passed','checks':checks,'baselineRunId':args.baseline_run_id}
    env.save(output/'result.json',result);print(output.name)


if __name__=='__main__':main()
