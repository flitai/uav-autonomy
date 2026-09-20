"""Independent numerical checks and refusal probes; synthetic != data qualification."""
import argparse
import gzip
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import traceback

import numpy as np
from PIL import Image
import pyproj
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g5_geography'))
from pmtiles import directory, inflate, inspect_mvt, tile_id, varints
from recheck import independent_rgb, recheck
from sources import decode_png, need, provenance_tiles, required_tiles, save, sha
from terrain import Terrain, VerticalTransform, derive, guard, validate_dted, write_raster


def rejected(call):
    try:call()
    except (ValueError,RuntimeError,FileNotFoundError,pyproj.exceptions.ProjError,OSError):return
    raise AssertionError('Invalid input was accepted')


def grid_reference(grid,lon,lat):
    """GDAL raster georeference and scalar bilinear geoid, independent of PROJ."""
    with rasterio.open(grid) as source:
        column,row=(~source.transform)*(lon,lat);column-=.5;row-=.5
        x,y=math.floor(column),math.floor(row);dx,dy=column-x,row-y
        a=source.read(1,window=((y,y+2),(x,x+2))).astype(float)
    return a[0,0]*(1-dx)*(1-dy)+a[0,1]*dx*(1-dy)+a[1,0]*(1-dx)*dy+a[1,1]*dx*dy


def run(command,folder,label):
    proc=subprocess.run(list(map(str,command)),cwd=folder,capture_output=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
    (folder/(label+'.stdout')).write_bytes(proc.stdout);(folder/(label+'.stderr')).write_bytes(proc.stderr)
    need(proc.returncode==0,label+' failed');return proc.stdout.decode('utf-8')


def cesium_reference(root,candidate,output,ellipsoid):
    pointer=json.loads((root/'.tools/g5/current.json').read_text());environment=root/pointer['path']
    project=output/'Cesium 中文 probe';project.mkdir()
    for name in ('package.json','package-lock.json','.npmrc'):shutil.copyfile(root/'apps/cesium_viewer'/name,project/name)
    # npm consumes the fixed integrity lock and verifies cached package bytes;
    # no existing node_modules directory is trusted as an independent probe.
    env=dict(os.environ);env['PATH']=str(environment/'node')+os.pathsep+env.get('PATH','')
    env.update(NPM_CONFIG_CACHE=str(root/'.tools/cache/g5/npm'),NPM_CONFIG_USERCONFIG=str(project/'.npmrc'),
               NPM_CONFIG_GLOBALCONFIG=os.devnull)
    command=[environment/'node/node.exe',environment/'node/node_modules/npm/bin/npm-cli.js','ci','--ignore-scripts','--offline','--no-audit','--no-fund']
    proc=subprocess.run(list(map(str,command)),cwd=project,env=env,capture_output=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
    (output/'cesium-npm.stdout').write_bytes(proc.stdout);(output/'cesium-npm.stderr').write_bytes(proc.stderr)
    need(proc.returncode==0,'Locked offline Cesium probe install failed')
    points=[(-121.99,45.011),(-121.001,45.499),(-121,45.5),(-120.05,45.829),(-121.8753,45.50017)]
    save(output/'cesium-request.json',dict(path=str(candidate/'cesium-heightfield.f32'),width=2401,height=1201,
        bounds=dict(west=-122,south=45,east=-120,north=46),points=points))
    run([environment/'node/node.exe',root/'tests/g5_geography/cesium_probe.mjs',project,output/'cesium-request.json',output/'cesium-response.json'],output,'cesium')
    actual=json.loads((output/'cesium-response.json').read_text())['values'];errors=[]
    # Barycentric planes over SW/NE diagonal, independently evaluated as a
    # three-vertex linear system, not by copying Cesium's interpolation function.
    for (lon,lat),height in zip(points,actual):
        x=(lon+122)*1200;y=(lat-45)*1200;ix,iy=math.floor(x),math.floor(y);dx,dy=x-ix,y-iy
        if dy>dx:
            vertices=[(0,0),(0,1),(1,1)];values=[ellipsoid[1200-iy,ix],ellipsoid[1199-iy,ix],ellipsoid[1199-iy,ix+1]]
        else:
            vertices=[(0,0),(1,0),(1,1)];values=[ellipsoid[1200-iy,ix],ellipsoid[1200-iy,ix+1],ellipsoid[1199-iy,ix+1]]
        coefficients=np.linalg.solve(np.array([[a,b,1] for a,b in vertices]),values)
        expected=float(coefficients @ np.array([dx,dy,1]));errors.append(abs(height-expected))
    need(max(errors)<1e-6,'Actual Cesium triangular interpolation differs')
    return dict(samples=len(points),maxErrorMeters=max(errors),packageLockSHA256=sha(project/'package-lock.json'),
                heightmapSourceSHA256=sha(project/'node_modules/@cesium/engine/Source/Core/HeightmapTerrainData.js'))


def numeric(root,candidate,output):
    config=json.loads((root/'config/g5-terrain.json').read_text());lock=json.loads((root/'config/g5-geography-lock.json').read_text())
    grid=root/'out/geography/input-cache'/lock['geoid']['filename']
    with rasterio.open(candidate/'orthometric.tif') as source:
        h=source.read(1).astype(float);transform=source.transform
        need(h.shape==(1201,2401) and source.tags().get('AREA_OR_POINT')=='Point','Normalized grid layout')
        np.testing.assert_allclose(transform*(.5,.5),(-122,46),atol=1e-12)
    ellipsoid=np.fromfile(candidate/'cesium-heightfield.f32',dtype='<f4').reshape(h.shape)
    for x in range(2):
        path=candidate/'dted'/('w'+str(122-x))/'n45.dt1';validate_dted(path)
        with rasterio.Env(DTED_VERIFY_CHECKSUM='YES',DTED_ASSUME_CONFORMANT='TRUE'):
            with rasterio.open(path) as source:
                np.testing.assert_allclose(source.read(1),np.rint(h[:,x*1200:x*1200+1201]),atol=1)
    points=[(-121.8,45.15),(-121.001,45.499),(-121,45.5),(-120.05,45.82)]
    errors=[];geoid=[]
    for lon,lat in points:
        x=int(round((lon+122)*1200));y=int(round((46-lat)*1200));lon=-122+x/1200;lat=46-y/1200
        n=grid_reference(grid,lon,lat);geoid.append(n);errors.append(abs(ellipsoid[y,x]-h[y,x]-n))
    need(max(errors)<.001,'Independent geoid conversion/sign differs')
    # Query the unchanged formal AMASE JAR, including an internal cell boundary.
    javac=root/'.tools/jdk-11.0.32.1+1/bin/javac.exe';java=javac.with_name('java.exe');jar=root/'out/artifacts/amase/OpenAMASE.jar'
    run([javac,'-encoding','UTF-8','-cp',jar,'-d',output,root/'tests/g5_geography/DtedProbe.java'],output,'javac')
    request=output/'java-query.tsv';request.write_text('\n'.join(
        str(candidate/'dted'/('w'+str(abs(math.floor(lon))))/'n45.dt1')+'\t'+str(lat)+'\t'+str(lon) for lon,lat in points)+'\n')
    stdout=run([java,'-Djava.awt.headless=true','-cp',str(output)+';'+str(jar),'DtedProbe',request],output,'java-query')
    need('out/artifacts/amase/OpenAMASE.jar' in stdout.splitlines()[0].replace('\\','/'),'Unexpected AMASE class source')
    nearest_errors=[];bilinear_errors=[]
    rounded=np.rint(h)
    for line,(lon,lat) in zip(stdout.splitlines()[1:],points):
        fields=line.split('\t');px=(lon+122)*1200;py=(lat-45)*1200
        cx,cy=int(math.floor(px+.5)),1200-int(math.floor(py+.5))
        nearest_errors.append(abs(float(fields[3])-rounded[cy,cx]))
        x0,y0=math.floor(px),math.floor(py);dx,dy=px-x0,py-y0
        q=rounded[1200-y0,x0]*(1-dx)*(1-dy)+rounded[1200-y0,x0+1]*dx*(1-dy)+rounded[1199-y0,x0]*(1-dx)*dy+rounded[1199-y0,x0+1]*dx*dy
        bilinear_errors.append(abs(float(fields[4])-q))
    need(max(nearest_errors)<1e-8 and max(bilinear_errors)<1e-7,'AMASE queries differ')
    cesium=cesium_reference(root,candidate,output,ellipsoid)
    return dict(nodes=1201*2401,geoidOffsetsMeters=geoid,maxGeoidDifferenceMeters=max(errors),cesium=cesium,
                amaseNearestError=max(nearest_errors),amaseBilinearError=max(bilinear_errors),
                amaseJarSHA256=sha(jar),interpolationMethodsComparedSeparately=True,
                amaseSpacingMetadataIssue='Reader reports 10x spacing; queries derive spacing from post counts')


def validate(root,candidate,output):
    """Only called after an unchanged successful candidate entry."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('g5_regional_checks',root/'tests/g5_geography/regional_checks.py')
    checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)
    legacy_output=output/'legacy-core';legacy_output.mkdir()
    legacy=core(root,legacy_output)
    return [dict(name='independent-same-source-and-AMASE',**numeric(root,candidate,output)),
            dict(name='legacy-format-corruption-and-negative-height-guards',checks=legacy['checks'],dataQualified=False),
            *checks.validate(root,candidate,output)]


def core(root,output):
    config=json.loads((root/'config/g5-terrarium-legacy.json').read_text());lock=json.loads((root/'config/g5-geography-lock.json').read_text())
    grid=root/'out/geography/input-cache'/lock['geoid']['filename'];checks=[]
    def check(name,call):call();checks.append(name)
    for name,data in [('truncated-varint',b'\x80'),('overflow-varint',b'\xff'*10+b'\x00')]:
        check(name,lambda d=data:rejected(lambda:varints(d)))
    check('gzip-limit',lambda:rejected(lambda:inflate(gzip.compress(b'x'*100),32)))
    check('truncated-gzip',lambda:rejected(lambda:inflate(gzip.compress(b'x')[:-2])))
    check('directory-shape',lambda:rejected(lambda:directory(gzip.compress(b'\x02\x00'))))
    check('bad-mvt',lambda:rejected(lambda:inspect_mvt(b'\x1a\x7f')))
    check('Hilbert-known-order',lambda:np.testing.assert_equal([tile_id(1,x,y) for x,y in [(0,0),(0,1),(1,1),(1,0)]],[1,2,3,4]))
    diagnostic=recheck(root,output,online=False)
    check('three-independent-real-PNG-decoders',lambda:need(diagnostic['heightMeters']==-4037,'Frozen anomaly changed'))
    raw=(root/'tiles/dem/10/170/365.png').read_bytes();bad=output/'bad.png';bad.write_bytes(raw[:-20])
    check('truncated-PNG',lambda:rejected(lambda:decode_png(bad)))
    damaged=bytearray(raw);damaged[100]^=1;bad.write_bytes(damaged)
    check('PNG-CRC',lambda:rejected(lambda:decode_png(bad)))
    zero=output/'nodata.png';Image.fromarray(np.zeros((256,256,3),dtype=np.uint8)).save(zero)
    check('Terrarium-nodata',lambda:rejected(lambda:decode_png(zero)))
    check('missing-PNG',lambda:rejected(lambda:decode_png(output/'absent.png')))
    vertical=VerticalTransform(grid,lock['geoid']['sha256'])
    for datum in ('EPSG:4979','unknown','AGL'):
        check('reject-height-datum-'+datum,lambda d=datum:rejected(lambda:vertical.ellipsoid(-121,45.5,100,d)))
    check('missing-grid',lambda:rejected(lambda:VerticalTransform(output/'missing.tif','0'*64)))
    check('changed-grid',lambda:rejected(lambda:VerticalTransform(grid,'0'*64)))
    check('outside-qualified-region',lambda:rejected(lambda:guard(config,-120,45.5)))
    check('latitude-longitude-swap',lambda:rejected(lambda:guard(config,45.5,-121)))
    n=grid_reference(grid,-121,45.5)
    check('positive-negative-heights-and-geoid-sign',lambda:np.testing.assert_allclose(
        [vertical.ellipsoid(-121,45.5,h,'EPSG:5773') for h in (-100,0,100)],np.array([-100,0,100])+n,atol=1e-8))
    tiles=required_tiles(config['bounds'],10);source=Terrain(root,config,tiles)
    check('unqualified-tile',lambda:rejected(lambda:source.tile(1,1)))
    # Independent GDAL coordinate transform plus scalar raw-pixel interpolation.
    lon,lat=-120.16083333333333,45.751666666666665
    mx,my=pyproj.Transformer.from_crs(4326,3857,always_xy=True).transform(lon,lat)
    resolution=2*math.pi*6378137/(256*1024);px=(mx+math.pi*6378137)/resolution-.5;py=(math.pi*6378137-my)/resolution-.5
    ix,iy=math.floor(px),math.floor(py);dx,dy=px-ix,py-iy
    def pixel(x,y):
        b=independent_rgb((root/f'tiles/dem/10/{x//256}/{y//256}.png').read_bytes())[y%256,x%256]
        return int(b[0])*256+int(b[1])+int(b[2])/256-32768
    reference=pixel(ix,iy)*(1-dx)*(1-dy)+pixel(ix+1,iy)*dx*(1-dy)+pixel(ix,iy+1)*(1-dx)*dy+pixel(ix+1,iy+1)*dx*dy
    check('independent-raw-to-normalized-anomaly',lambda:np.testing.assert_allclose(source.sample(lon,lat),reference,atol=1e-6))
    synthetic=root/'out/tmp'/output.name/'合成 地形';synthetic.mkdir(parents=True,exist_ok=False)
    for z,x,y in tiles:
        columns,rows=np.meshgrid(np.arange(256),np.arange(256));heights=250+(x*256+columns-164*256)*.5+(y*256+rows-364*256)*.25
        encoded=heights+32768;rgb=np.stack([encoded//256,encoded%256,(encoded*256)%256],axis=-1).astype(np.uint8)
        folder=synthetic/f'tiles/dem/{z}/{x}';folder.mkdir(parents=True,exist_ok=True);Image.fromarray(rgb).save(folder/f'{y}.png')
    derived=output/'synthetic-derived';derived.mkdir()
    derive(synthetic,derived,config,tiles,grid,lock['geoid']['sha256'])
    checks.append('synthetic-full-derivation-Chinese-space-path')
    numbers=numeric(root,derived,output);checks.append('synthetic-independent-grid-geoid-DTED-AMASE')
    negative=output/'negative.tif';write_raster(negative,np.full((1201,1201),-100,dtype=np.int16),from_origin(-122-.5/1200,46+.5/1200,1/1200,1/1200))
    raster_copy(negative,output/'negative.dt1',driver='DTED')
    check('negative-DTED-guard',lambda:rejected(lambda:validate_dted(output/'negative.dt1')))
    validate_dted(output/'negative.dt1',nonnegative=False)
    request=output/'negative-query.tsv';request.write_text(str(output/'negative.dt1')+'\t45.5\t-121.5\n')
    jar=root/'out/artifacts/amase/OpenAMASE.jar'
    text=run([root/'.tools/jdk-11.0.32.1+1/bin/java.exe','-Djava.awt.headless=true','-cp',str(output)+';'+str(jar),'DtedProbe',request],output,'java-negative')
    observed=int(text.splitlines()[1].split('\t')[3])
    need(observed==-32668,'AMASE negative limitation changed; review required')
    result=dict(status='passed',scope='implementation probes only; synthetic outputs cannot qualify real data',
                dataQualified=False,checks=checks,numeric=numbers,independentAnomalyHeight=reference,
                amaseNegativeKnownFailure=dict(dtedValue=-100,observed=observed),projNetworkEnabled=pyproj.network.is_network_enabled())
    save(output/'core-result.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:print(json.dumps(core(args.root.resolve(),args.output.resolve()),indent=2))
    except BaseException as error:
        save(args.output/'core-result.json',dict(status='failed',dataQualified=False,error=str(error),traceback=traceback.format_exc()))
        raise
