"""A real partial final matrix must not qualify or change the published pointer."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--run-id',required=True)
    args=parser.parse_args(); root=args.root.resolve()
    publisher=module('premature_publisher',root/'scripts/g4_stage/publish.py'); package=publisher.package
    source=root/'out/runs'/args.run_id/'result.json'; raw=source.read_bytes(); receipt=package.load(source)
    assert receipt['status']=='running' and receipt['cases'] and receipt['cases'][0]['status']=='passed'
    pointer=root/'out/artifacts/gis-gateway/current.json'; before=pointer.read_bytes() if pointer.exists() else None
    error=None
    try: publisher.validate_run(root,args.run_id,root/receipt['candidate'],receipt['packageSHA256'],'Original')
    except RuntimeError as rejected: error=str(rejected)
    assert error=='Unqualified final run',error
    assert before==(pointer.read_bytes() if pointer.exists() else None)
    directory=root/'out/runs'/('g4-t09-premature-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')); directory.mkdir()
    (directory/'observed-partial-result.json').write_bytes(raw)
    package.save(directory/'result.json',dict(status='passed',runId=args.run_id,rejection=error,
        partialReceiptSHA256=package.sha(directory/'observed-partial-result.json'),publishedPointerUnchanged=True,
        sources=package.files(root,[Path(__file__),root/'scripts/g4_stage/publish.py',root/'scripts/g4_stage/package.py'])))
    print(directory.name+' passed')


if __name__=='__main__': main()
