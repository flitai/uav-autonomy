"""Compile/run deterministic statistics or TCP checks against an explicit artifact."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True); parser.add_argument('--amase',type=Path,required=True)
    parser.add_argument('--java-home',type=Path,required=True)
    parser.add_argument('--suite',choices=['statistics','tcp'],default='statistics')
    args=parser.parse_args(); root=args.root.resolve(); artifact=args.amase.resolve()
    run_id='g4-t07-'+args.suite+'-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output=root/'out/runs'/run_id; output.mkdir(); classes=output/'classes'; classes.mkdir()
    spec=importlib.util.spec_from_file_location('statistics_amase',root/'scripts/amase/amase.py')
    amase=importlib.util.module_from_spec(spec); spec.loader.exec_module(amase)
    cp=[artifact,root/'out/artifacts/lmcp/java/lmcplib.jar']+[root/amase.PROJECT/p for p in amase.LIBRARIES]
    class_name='avtas.amase.analysis.SearchChecks' if args.suite=='statistics' else 'avtas.amase.network.TcpFanoutChecks'
    source=root/'tests/g4_mixed'/(class_name.rsplit('.',1)[1]+'.java')
    record={'status':'running','runId':run_id,'scope':'deterministic-'+args.suite+'-only',
            'inputs':[{'path':str(p.relative_to(root)),'sha256':sha(p)} for p in [Path(__file__).resolve(),source,*cp]]}
    def invoke(label,arguments):
        process=subprocess.run(list(map(str,arguments)),cwd=output,capture_output=True,timeout=60,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        (output/(label+'.stdout')).write_bytes(process.stdout); (output/(label+'.stderr')).write_bytes(process.stderr)
        record[label+'ExitCode']=process.returncode
        if process.returncode: raise RuntimeError(label+' failed; see captured output')
    try:
        invoke('javac',[args.java_home/'bin/javac.exe','-encoding','UTF-8','--release','11','-cp',os.pathsep.join(map(str,cp)),
                        '-d',classes,source])
        invoke('java',[args.java_home/'bin/java.exe','-Dfile.encoding=UTF-8','-Djava.awt.headless=true','-cp',
                       os.pathsep.join(map(str,[classes,*cp])),class_name,output/'checks.xml'])
        record['status']='passed'; return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc()); return 1
    finally:
        record['evidence']=[{'path':p.name,'sha256':sha(p)} for p in sorted(output.iterdir()) if p.is_file()]
        (output/'result.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record,indent=2),flush=True); print('G4_T07_STATISTICS_RUN_ID='+run_id,flush=True)


if __name__=='__main__': sys.exit(main())
