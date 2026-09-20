"""Reject unrelated or automatic confirmation in the narrow controlled finalization."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--confirmation',type=Path,required=True); args=parser.parse_args(); root=args.root.resolve()
    spec=importlib.util.spec_from_file_location('finalization_checks',root/'scripts/g4_finalize/receipts.py')
    receipts=importlib.util.module_from_spec(spec); spec.loader.exec_module(receipts)
    confirmation=receipts.load(args.confirmation); positive=receipts.visual(root,confirmation); checks=[]
    for key,value in [('visualRunId','old-run'),('visualResultSHA256','0'*64),('visualReviewSHA256','0'*64),
                      ('packageSHA256','0'*64),('confirmationSource','automatic'),('confirmationText',''),
                      ('confirmedAtEpochSeconds',0),('scope','all-future-runs')]:
        try: receipts.visual(root,{**confirmation,key:value})
        except RuntimeError as error: checks.append(dict(field=key,status='passed',rejection=str(error)))
        else: raise AssertionError('Unexpected visual acceptance: '+key)
    assert positive['visualRunStatus']=='failed' and positive['visualNormalExit'] and positive['completeControlledRerunRequired']
    directory=root/'out/runs'/('g4-t09-finalization-checks-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')); directory.mkdir()
    receipts.save(directory/'result.json',dict(status='passed',checks=checks,positive=positive,
        confirmationSHA256=receipts.sha(args.confirmation),sources=receipts.package.files(root,[Path(__file__),root/'scripts/g4_finalize/receipts.py'])))
    print(directory.name+' passed '+str(len(checks)))


if __name__=='__main__': main()
