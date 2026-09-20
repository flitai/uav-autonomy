"""Bounded-memory full-file digest; raw geographic inputs are opened read-only."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time


def full_digest(path, progress=None):
    before = path.stat(); digest = hashlib.sha256(); count = 0; start = time.monotonic(); report = start
    with path.open('rb', buffering=0) as stream:
        while data := stream.read(8*1024*1024):
            digest.update(data); count += len(data)
            if progress and time.monotonic()-report >= 15:
                progress(dict(bytesRead=count, totalBytes=before.st_size, elapsedSeconds=time.monotonic()-start))
                report = time.monotonic()
    after = path.stat()
    if count != before.st_size or (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
        raise RuntimeError('Raw input changed while hashing: '+str(path))
    return dict(bytes=count, modifiedNs=str(before.st_mtime_ns), sha256=digest.hexdigest(),
                fullContentHashed=True, elapsedSeconds=time.monotonic()-start)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve();args.output.mkdir(parents=True,exist_ok=False)
    record=dict(status='running',startedAt=datetime.now().isoformat(),
                implementationSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),files=[])
    try:
        for name in ('tiles/tiles/planet.pmtiles','tiles/tiles/global-z9.pmtiles'):
            def report(value):
                (args.output/'progress.json').write_text(json.dumps(dict(path=name,**value)),encoding='utf-8')
                print(name,round(value['bytesRead']/value['totalBytes']*100,1),'%',flush=True)
            record['files'].append(dict(path=name,**full_digest(root/name,report)))
        record['status']='passed'
    except BaseException as error:
        record.update(status='failed',error=str(error));raise
    finally:
        (args.output/'result.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
