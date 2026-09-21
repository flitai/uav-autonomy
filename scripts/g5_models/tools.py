"""Project-local, pinned Windows OSGB reader build. No global installation."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import traceback
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('g5_model_base',ROOT/'scripts/g5_environment/common.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
load,save,sha,need=base.load,base.save,base.sha,base.need

def inputs():
    paths=[ROOT/'scripts/g5_models/native/CMakeLists.txt',ROOT/'scripts/g5_models/native/reader.cpp',
        ROOT/'scripts/g5_models/tools.py',ROOT/'config/g5-model-toolchain.json',ROOT/'config/windows-cpp-toolchain.json',ROOT/'scripts/windows/setup-g5-models.ps1']
    return base.inventory(ROOT,paths)

def resolve():
    pointer=load(ROOT/'.tools/g5-models/current.json');package=ROOT/pointer['path']
    need(sha(package/'manifest.json')==pointer['manifestSHA256'],'Model tool pointer differs')
    manifest=load(package/'manifest.json');need(manifest['status']=='passed' and manifest['inputs']==inputs(),'Model tool inputs differ; rebuild')
    base.verify_files(ROOT,manifest['inputs']);base.verify_files(package,manifest['files'])
    return package,manifest,pointer

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--cmake');p.add_argument('--ninja');p.add_argument('--verify',action='store_true');a=p.parse_args()
    run=ROOT/'out/runs'/a.run_id;record=dict(task='G5-T06-model-tools',status='running',runId=a.run_id)
    try:
        if a.verify:
            package,manifest,pointer=resolve();record.update(package=pointer);return 0
        frozen_inputs=inputs()
        config=load(ROOT/'config/g5-model-toolchain.json');directory=ROOT/'.tools/g5-models';archive=directory/'downloads'/config['archive'];archive.parent.mkdir(parents=True,exist_ok=True)
        if not archive.exists():
            with urlopen(config['url'],timeout=60) as response:archive.write_bytes(response.read())
        need(sha(archive)==config['sha256'] and hashlib.sha512(archive.read_bytes()).hexdigest()==config['sha512'],'OSG archive checksum differs')
        source=directory/'source'/config['sourceDirectory']
        if not source.exists():
            with tarfile.open(archive) as bundle:bundle.extractall(source.parent,filter='data')
        # Compare every upstream source member to the independently locked archive.
        with tarfile.open(archive) as bundle:
            for member in bundle:
                if not member.isfile():continue
                path=source.parent/member.name
                need(path.resolve().is_relative_to(source.resolve()) and path.is_file(),'Unsafe/missing OSG source')
                need(hashlib.sha256(bundle.extractfile(member).read()).hexdigest()==sha(path),'Modified OSG source: '+member.name)
        build=directory/'build'/a.run_id;build.mkdir(parents=True)
        command=[a.cmake,'-S',str(ROOT/'scripts/g5_models/native'),'-B',str(build),'-G','Ninja','-DOSG_SOURCE='+str(source),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_MAKE_PROGRAM='+a.ninja]
        base.invoke(command,run,'configure',timeout=180)
        base.invoke([a.cmake,'--build',build,'--target',*config['targets'],'--parallel','8'],run,'build',timeout=900)
        package=directory/'packages'/a.run_id;package.mkdir(parents=True)
        paths=[build/'bin/g5-model-reader.exe',*list((build/'osg/bin').glob('*.dll')),build/'osg/src/osgPlugins/osg/osgdb_osg.dll',build/'osg/src/osgWrappers/serializers/osg/osgdb_serializers_osg.dll']
        for path in paths:need(path.is_file(),'Missing reader runtime');shutil.copy2(path,package/path.name)
        license_path=source/'LICENSE.txt';need(license_path.is_file(),'Missing OSG license');shutil.copy2(license_path,package/'OpenSceneGraph-LICENSE.txt')
        need(inputs()==frozen_inputs,'Model tool sources changed during build')
        manifest=dict(status='passed',runId=a.run_id,version=config['version'],archiveSHA256=sha(archive),inputs=frozen_inputs,
            compiler={'cmake':a.cmake,'ninja':a.ninja,'cacheSHA256':sha(build/'CMakeCache.txt')},files=base.inventory(package,[x for x in package.iterdir() if x.is_file()]))
        save(package/'manifest.json',manifest)
        pointer=dict(path=package.relative_to(ROOT).as_posix(),manifestSHA256=sha(package/'manifest.json'),runId=a.run_id)
        temporary=directory/'current.new.json';save(temporary,pointer);os.replace(temporary,directory/'current.json')
        record.update(package=pointer);return 0
    except Exception as error:record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(record['traceback']);return 1
    finally:
        if record['status']=='running':record['status']='passed'
        save(run/'result.json',record);print('G5_MODEL_TOOLS_RESULT='+str(run/'result.json'))

if __name__=='__main__':sys.exit(main())
