"""Launch the exact bundle bytes; backend lifecycle remains independent."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()
def need(value,message):
    if not value: raise RuntimeError(message)


def main():
    parser=argparse.ArgumentParser()
    for key in ('root','manifest','output'): parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--manifest-sha256',required=True)
    parser.add_argument('--package-sha256',required=True)
    args=parser.parse_args(); args.root=args.root.resolve()
    bundle=Path(__file__).resolve().parents[2]
    need(sha(bundle/'package.json')==args.package_sha256,'Untrusted package manifest')
    package=json.loads((bundle/'package.json').read_text(encoding='utf-8'))
    for base,key in ((bundle,'packageFiles'),(args.root,'workspaceFiles')):
        for row in package[key]:
            path=(base/row['path']).resolve()
            need(path.is_relative_to(base) and sha(path)==row['sha256'],'Package dependency differs: '+row['path'])
    need(Path(sys.executable).resolve()==Path(package['pythonExecutable']).resolve(),'Wrong gateway environment')
    spec=importlib.util.spec_from_file_location('qualified_environment',args.root/'scripts/g4_environment/manage.py')
    environment=importlib.util.module_from_spec(spec); spec.loader.exec_module(environment)
    need(environment.environment(args.root)[0].resolve()==Path(sys.executable).resolve(),'Installed dependencies changed')
    spec=importlib.util.spec_from_file_location('qualified_gateway_server',bundle/'apps/gis_gateway/server.py')
    server=importlib.util.module_from_spec(spec); spec.loader.exec_module(server)
    loaded=[]
    for name,value in sorted(sys.modules.items()):
        if name.startswith('sim_bridge.'):
            path=Path(value.__file__).resolve()
            need(path.is_relative_to(bundle/'src/sim_bridge'),'Gateway loaded workspace core: '+name)
            loaded.append({'module':name,'path':str(path),'sha256':sha(path)})
    need(loaded,'Gateway core was not imported')
    receipt={'packageSHA256':args.package_sha256,'bundle':str(bundle),'python':sys.executable,'loaded':loaded}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    target=args.output.parent/'package-launch.json'
    with target.open('x',encoding='utf-8') as stream: json.dump(receipt,stream,indent=2)
    import asyncio
    return asyncio.run(server.run(args))


if __name__=='__main__': sys.exit(main())
