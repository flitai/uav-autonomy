"""Replay accepted WaterwaySearch records through a candidate analysis artifact."""
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
import xml.etree.ElementTree as ET


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def semantic(node): return (node.tag,sorted(node.attrib.items()),(node.text or '').strip(),[semantic(n) for n in node])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--amase',type=Path,required=True); parser.add_argument('--java-home',type=Path,required=True)
    args=parser.parse_args(); root=args.root.resolve(); artifact=args.amase.resolve(); java=args.java_home.resolve()
    identity='g4-t07-line-replay-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output=root/'out/runs'/identity; output.mkdir(); classes=output/'classes'; classes.mkdir()
    spec=importlib.util.spec_from_file_location('line_regression_amase',root/'scripts/amase/amase.py')
    amase=importlib.util.module_from_spec(spec); spec.loader.exec_module(amase)
    cp=[artifact,root/'out/artifacts/lmcp/java/lmcplib.jar']+[root/amase.PROJECT/p for p in amase.LIBRARIES]
    sources=[root/'tests/g3_completion'/name for name in ('CoverageChecks.java','AnalysisReplay.java')]
    record={'status':'running','runId':identity,'scope':'candidate-analysis-regression',
            'inputs':[{'path':p.relative_to(root).as_posix(),'sha256':sha(p)} for p in [Path(__file__).resolve(),*sources,*cp]],'cases':[]}
    def invoke(name,argv):
        result=subprocess.run(list(map(str,argv)),cwd=output,capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        (output/(name+'.stdout')).write_bytes(result.stdout); (output/(name+'.stderr')).write_bytes(result.stderr)
        if result.returncode: raise RuntimeError(name+' failed: '+str(result.returncode))
    try:
        parent=root/'out/runs/g4-t06-test-20260920-010936-703'; receipt=load(parent/'result.json')
        assert receipt['status']==load(parent/'entry-result.json')['status']=='passed'
        record['parent']={'runId':receipt['runId'],'resultSHA256':sha(parent/'result.json')}
        invoke('compile',[java/'bin/javac.exe','-encoding','UTF-8','--release','11','-cp',os.pathsep.join(map(str,cp)),'-d',classes,*sources])
        base=[java/'bin/java.exe','-Dfile.encoding=UTF-8','-cp',os.pathsep.join(map(str,[classes,*cp]))]
        invoke('fixtures',[*base,'-Djava.awt.headless=true','avtas.amase.analysis.CoverageChecks',output/'checks.xml'])
        for case in receipt['cases']:
            directory=parent/case['name']; expected={row['path']:row['sha256'].lower() for row in case['evidence']}
            for name in ('amase/analysis-events.tsv','amase/config/Plugins.xml','amase/analysis.xml',
                         'replay-headless/pixels.csv','replay-gui/pixels.csv'):
                assert sha(directory/name)==expected[name]
            original=semantic(ET.parse(directory/'amase/analysis.xml').find('SearchTaskAnalysis'))
            for mode in ('headless','gui'):
                label=case['name']+'-'+mode; target=output/label
                invoke(label,[*base,'-Djava.awt.headless='+str(mode=='headless').lower(),'avtas.amase.analysis.AnalysisReplay',
                    directory/'amase/analysis-events.tsv',directory/'amase/config/Plugins.xml',target])
                for name in ('analysis.xml','incremental.xml','reset-replay.xml'):
                    assert semantic(ET.parse(target/name).find('SearchTaskAnalysis'))==original
                assert (target/'pixels.csv').read_bytes()==(directory/('replay-'+mode)/'pixels.csv').read_bytes()
                record['cases'].append({'case':label,'status':'passed','originalReportAndPixelsMatched':True})
        record['status']='passed'; return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc()); return 1
    finally:
        record['evidence']=[{'path':p.relative_to(output).as_posix(),'sha256':sha(p)} for p in sorted(output.rglob('*')) if p.is_file()]
        (output/'result.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in record.items() if k not in ('inputs','evidence')},indent=2),flush=True)


if __name__=='__main__': sys.exit(main())
