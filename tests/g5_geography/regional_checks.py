"""Scalar source, grid-polynomial, ECEF and Helmert references independent of PROJ."""
import argparse
import copy
import json
import math
from pathlib import Path
import sys
import traceback

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g5_geography'))
from regional import Conversion, Primary, RasterSet, load, read_pixels, verify_sources
from sources import need, save
from terrain import guard


def scalar_grid(path,lon,lat,band=1,quadratic=False):
    with rasterio.open(path) as ds:
        if ds.bounds.left>180:lon=lon%360
        x,y=(~ds.transform)*(lon,lat);x-=.5;y-=.5
        if not quadratic:
            c,r=math.floor(x),math.floor(y);dx,dy=x-c,y-r
            a=ds.read(band,window=((r,r+2),(c,c+2))).astype(float)
            need(a.shape==(2,2),'Reference grid footprint incomplete')
            return float(a[0,0]*(1-dx)*(1-dy)+a[0,1]*dx*(1-dy)+a[1,0]*(1-dx)*dy+a[1,1]*dx*dy)
        # Tensor-product Lagrange polynomials through the nearest 3x3 posts.
        c,r=int(math.floor(x+.5)),int(math.floor(y+.5))
        a=ds.read(band,window=((r-1,r+2),(c-1,c+2))).astype(float)
        need(a.shape==(3,3),'Reference NADCON5 footprint incomplete')
        def weights(t):return np.array([t*(t-1)/2,1-t*t,t*(t+1)/2])
        return float(weights(y-r) @ a @ weights(x-c))


def cartesian(lon,lat,h,inverse_flattening):
    a=6378137.;f=1/inverse_flattening;e2=f*(2-f)
    phi,lam=math.radians(lat),math.radians(lon)
    n=a/math.sqrt(1-e2*math.sin(phi)**2)
    return np.array([(n+h)*math.cos(phi)*math.cos(lam),(n+h)*math.cos(phi)*math.sin(lam),
                     (n*(1-e2)+h)*math.sin(phi)])


def geographic(xyz):
    x,y,z=xyz;a=6378137.;f=1/298.257223563;e2=f*(2-f);p=math.hypot(x,y)
    phi=math.atan2(z,p*(1-e2))
    for _ in range(12):
        n=a/math.sqrt(1-e2*math.sin(phi)**2)
        phi=math.atan2(z+e2*n*math.sin(phi),p)
    n=a/math.sqrt(1-e2*math.sin(phi)**2)
    return math.degrees(math.atan2(y,x)),math.degrees(phi),p/math.cos(phi)-n


def reference_compound(cache,lon,lat,height):
    shift=cache/'us_noaa_nadcon5_nad83_1986_nad83_harn_conus.tif'
    latitude=lat+scalar_grid(shift,lon,lat,1,True)/3600
    longitude=lon+scalar_grid(shift,lon,lat,2,True)/3600
    ellipsoid=height+scalar_grid(cache/'us_noaa_g1999u01.tif',longitude,latitude)
    xyz=cartesian(longitude,latitude,ellipsoid,298.257222101)
    # EPSG:1901, coordinate-frame convention, rotations in arcseconds.
    rx,ry,rz=np.radians(np.array([-.0257899075194932,-.0096500989602704,-.0116599432323421])/3600)
    rotation=np.array([[1,rz,-ry],[-rz,1,rx],[ry,-rx,1]])
    return geographic(rotation@xyz+np.array([-.991,1.9072,.5129]))


def native_reference(root,lock,lon,lat):
    files=sorted([r for r in lock['files'] if r['dataset']=='usgs-3dep-13arcsec' and r['kind']=='tif'],key=lambda r:r['path'],reverse=True)
    for row in files:
        with rasterio.open(root/row['path']) as ds:
            x,y=(~ds.transform)*(lon,lat);x-=.5;y-=.5
            c,r=math.floor(x),math.floor(y)
            if c<0 or c+1>=ds.width or r<0 or r+1>=ds.height:continue
            a=ds.read(1,window=((r,r+2),(c,c+2)),masked=True)
            need(not np.ma.getmaskarray(a).any(),'Reference native source has NoData')
            dx,dy=x-c,y-r
            value=float(a[0,0])*(1-dx)*(1-dy)+float(a[0,1])*dx*(1-dy)+float(a[1,0])*(1-dx)*dy+float(a[1,1])*dx*dy
            return value
    raise ValueError('Reference outside source coverage')


def normalized_reference(root,lock,lon,lat):
    cache=root/'out/geography/input-cache';sx,sy=lon,lat;best=None
    for _ in range(7):
        native=native_reference(root,lock,sx,sy)
        tx,ty,h=reference_compound(cache,sx,sy,native)
        residual=math.hypot(tx-lon,ty-lat)
        if best is None or residual<best[0]:best=(residual,h)
        sx+=lon-tx;sy+=lat-ty
    return best[1]-scalar_grid(cache/'us_nga_egm96_15.tif',lon,lat)


def rejected(call):
    try:call()
    except (ValueError,RuntimeError,OSError):return
    raise AssertionError('Invalid input accepted')


def validate(root,candidate,output):
    config=load(root/'config/g5-terrain.json');lock=load(root/'config/g5-regional-sources.json')
    verify_sources(root,lock);cache=root/'out/geography/input-cache';conversion=Conversion(root,lock)
    checks=[];references=[]
    points=[(-121.8,45.15,100),(-121,45.5,-100),(-120.16090393066405,45.75171424271876,144.5237274169922),
            (-121.95165365,45.324999986,447.15),(-121.5,45.9999,1700)]
    for lon,lat,h in points:
        expected=reference_compound(cache,lon,lat,h)
        actual=conversion.from_usgs(lon,lat,h)
        ecef_error=float(np.linalg.norm(cartesian(*expected,298.257223563)-cartesian(*actual,298.257223563)))
        need(ecef_error<1,'Independent compound reference exceeds 1 metre')
        references.append(dict(input=[lon,lat,h],independentWgs84=list(expected),projWgs84=list(actual),ecefErrorMeters=ecef_error))
    save(output/'independent-compound.json',references)
    checks.append(dict(name='independent-NADCON5-geoid99-ECEF-Helmert',samples=len(points),maxECEFErrorMeters=max(r['ecefErrorMeters'] for r in references)))
    with rasterio.open(candidate/'orthometric.tif') as ds:h=ds.read(1)
    nodes=[(0,0),(1200,2400),(600,1200),(600,1199),(600,1201),(298,2207),(810,58),(870,196),(930,262),(1199,2399)]
    samples=[]
    for y,x in nodes:
        lon=-122+x/1200;lat=46-y/1200;reference=normalized_reference(root,lock,lon,lat)
        difference=abs(float(h[y,x])-reference)
        need(difference<1,'Independent source-to-canonical post differs by more than 1 m')
        samples.append(dict(row=y,column=x,longitude=lon,latitude=lat,reference=reference,actual=float(h[y,x]),errorMeters=difference))
    save(output/'independent-normalized.json',samples)
    checks.append(dict(name='independent-source-to-canonical-posts',samples=len(samples),maxErrorMeters=max(s['errorMeters'] for s in samples)))
    with rasterio.open(candidate/'dted/w122/n45.dt1') as left,rasterio.open(candidate/'dted/w121/n45.dt1') as right:
        a=left.read(1);b=right.read(1)
        np.testing.assert_array_equal(a,np.rint(h[:,:1201]));np.testing.assert_array_equal(b,np.rint(h[:,1200:]))
        np.testing.assert_array_equal(a[:,-1],b[:,0])
    checks.append(dict(name='all-DTED-posts-and-shared-boundary',nodes=1201*2401,sharedPosts=1201))
    comparison=load(candidate/'copernicus-comparison.json')
    need(comparison['samples']==3321 and comparison['usedToFillPrimary'] is False,'Comparison changed primary data')
    # The complete comparison distribution is retained, without treating a DSM as truth.
    checks.append(dict(name='same-datum-Copernicus-comparison',**comparison))
    residual=load(candidate/'source-coordinate-residual.json')
    need(residual['maximumBoundMeters']<config['sourceHorizontalResidualLimitMeters']<=.05,'Source-coordinate residual guard failed')
    checks.append(dict(name='full-grid-source-coordinate-residual',**residual))
    refusals=[]
    def refuse(name,call):rejected(call);refusals.append(name)
    refuse('wrong-or-duplicate-datum',lambda:conversion.from_usgs(-121,45.5,100,'EPSG:4979'))
    refuse('unknown-geoid',lambda:conversion.geoid(-121,45.5,'unknown'))
    refuse('east-query-boundary',lambda:guard(config,-120,45.5))
    refuse('north-query-boundary',lambda:guard(config,-121,46))
    refuse('swapped-latitude-longitude',lambda:guard(config,45.5,-121))
    bad=copy.deepcopy(lock);bad['grids'][0]['sha256']='0'*64
    refuse('changed-grid-digest',lambda:Conversion(root,bad))
    bad=copy.deepcopy(lock);bad['sourceDownload']['sha256']='0'*64
    refuse('changed-download-receipt',lambda:verify_sources(root,bad))
    bad=copy.deepcopy(lock);bad['files'][0]['path']='out/geography/sources/missing.tif'
    refuse('missing-source',lambda:verify_sources(root,bad))
    fault=output/'nodata-source.tif'
    with rasterio.open(fault,'w',driver='GTiff',width=2,height=2,count=1,dtype='float32',nodata=-999999,
                       crs='EPSG:4269',transform=from_origin(-122,46,1/10800,1/10800)) as ds:
        ds.write(np.array([[100,200],[-999999,300]],dtype='float32'),1)
    with rasterio.open(fault) as ds:
        refuse('native-nodata',lambda:read_pixels(ds,np.array([1]),np.array([0])))
    cop=RasterSet(root,lock,'copernicus-glo30')
    try:
        need(np.isfinite(cop.sample_copernicus(np.array([-122,-120]),np.array([46,45]))).all(),'Outer comparison posts missing')
        cop.datasets=[(row,ds) for row,ds in cop.datasets if 'N44_00_W120' not in row['path']]
        refuse('missing-comparison-boundary',lambda:cop.sample_copernicus(-120,45))
    finally:cop.close()
    usgs=RasterSet(root,lock,'usgs-3dep-13arcsec')
    try:
        usgs.datasets=usgs.datasets[:1]
        refuse('missing-primary-without-Copernicus-fallback',lambda:usgs.sample_usgs(-120.1,45.5))
    finally:usgs.close()
    checks.append(dict(name='source-boundary-datum-and-corruption-refusals',checks=refusals))
    save(output/'regional-checks.json',dict(status='passed',checks=checks,simulationQualified=False))
    return checks


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:validate(args.root.resolve(),args.candidate.resolve(),args.output.resolve())
    except BaseException as error:
        save(args.output/'regional-failure.json',dict(status='failed',error=str(error),traceback=traceback.format_exc()));raise
