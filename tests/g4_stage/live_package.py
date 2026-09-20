"""Refuse a second packaged listener without disturbing the live owner."""
import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--run-id',required=True)
    parser.add_argument('--case',default='headless'); args=parser.parse_args(); root=args.root.resolve()
    spec=importlib.util.spec_from_file_location('live_package_helpers',root/'scripts/g4_stage/package.py')
    package=importlib.util.module_from_spec(spec); spec.loader.exec_module(package)
    record=package.load(root/'out/runs'/args.run_id/'result.json'); bundle=root/record['candidate']
    manifest=root/'out/runs'/args.run_id/args.case/'gateway-host/manifest.json'
    directory=root/'out/runs'/('g4-t09-live-package-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')); directory.mkdir()
    def health():
        with urlopen('http://127.0.0.1:8000/api/v1/health',timeout=3) as response: return json.load(response)
    before=health(); assert before['ready']
    output=directory/'second'/'observer'; metadata=package.load(bundle/'package.json')
    process=subprocess.run([metadata['pythonExecutable'],'-I','-B','-X','utf8',str(bundle/'scripts/g4_stage/launch.py'),
        '--root',str(root),'--manifest',str(manifest),'--manifest-sha256',package.sha(manifest),
        '--output',str(output),'--package-sha256',record['packageSHA256']],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    (directory/'stdout.log').write_bytes(process.stdout); (directory/'stderr.log').write_bytes(process.stderr)
    assert process.returncode!=0 and b'10048' in process.stderr and not output.exists()
    after=health(); assert after['ready'] and after['error'] is None
    assert all(before[key]==after[key] for key in ('run_id','stream_id'))
    package.save(directory/'result.json',dict(status='passed',before=before,after=after,refusedExitCode=process.returncode,
        packageSHA256=record['packageSHA256'],sourceSHA256=package.sha(Path(__file__))))
    print(directory.name+' passed')


if __name__=='__main__': main()
