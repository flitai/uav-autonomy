"""Record the user's actual visual run, without backdating or rewriting its failure."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import time


spec=importlib.util.spec_from_file_location('visual_receipts',Path(__file__).with_name('receipts.py'))
receipts=importlib.util.module_from_spec(spec); spec.loader.exec_module(receipts)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--confirmation-text',required=True); args=parser.parse_args(); root=args.root.resolve()
    proof=receipts.visual(root); policy=proof['policy']; receipts.need(args.confirmation_text.strip(),'User confirmation required')
    identity='g4-t09-visual-confirm-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    directory=root/'out/runs'/identity; directory.mkdir()
    record=dict(status='accepted-visual-only',scope='visual-only-same-version',confirmationSource='user',
        confirmationText=args.confirmation_text,confirmedAtEpochSeconds=time.time(),visualRunId=policy['visualRunId'],
        visualResultSHA256=policy['visualResultSHA256'],visualReviewSHA256=policy['visualReviewSHA256'],
        packageSHA256=policy['packageSHA256'],visualRunStatus='failed',proof=proof,controlledRerunRequired=True)
    receipts.visual(root,record); receipts.save(directory/'confirmation.json',record)
    print('G4_VISUAL_CONFIRMATION='+str(directory/'confirmation.json')); return 0


if __name__=='__main__': sys.exit(main())
