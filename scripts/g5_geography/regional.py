"""Locked USGS primary terrain and separately evaluated Copernicus DSM."""
from contextlib import ExitStack
import json
import math
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

import numpy as np
import pyproj
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin
from rasterio.windows import Window

from sources import fetch, need, save, sha
from terrain import guard, validate_dted, write_raster


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def verify_sources(root, lock):
    """Every current file must match the reviewed download, including provenance."""
    root=Path(root).resolve()
    source=lock['sourceDownload'];manifest_path=(root/source['path']).resolve()
    need(manifest_path.is_relative_to(root/'out/geography/sources') and sha(manifest_path)==source['sha256'],
         'Missing or changed source download receipt')
    receipt=load(manifest_path)
    need(receipt['status']=='download-integrity-verified' and receipt['terrainQualified'] is False,
         'Source download status differs')
    rows=lock['files']+lock['documents'];records=[]
    need(len(rows)==15 and len({r['path'] for r in rows})==15,'Incomplete or duplicate regional inputs')
    for row in rows:
        path=(root/row['path']).resolve()
        need(path.is_relative_to(root/'out/geography/sources') and path.is_file(), 'Missing/unsafe regional input')
        need(path.stat().st_size==row['bytes'] and sha(path)==row['sha256'],'Changed regional source: '+row['path'])
        records.append(dict(path=row['path'],sha256=row['sha256'],bytes=row['bytes']))
        if row.get('kind')=='xml':
            xml=ET.parse(path)
            need(xml.findtext('.//horizdn')=='North American Datum of 1983' and
                 xml.findtext('.//altdatum')=='North American Vertical Datum of 1988' and
                 xml.findtext('.//altunits').lower()=='meters','Unqualified USGS source datum/units')
        elif row.get('kind')=='gpkg':
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                need(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'Invalid source GeoPackage')
    need(sha(root/lock['operation']['path'])==lock['operation']['sha256'],'Changed coordinate operation definition')
    return dict(files=records,primary='usgs-3dep-13arcsec',comparison='copernicus-glo30',
                primaryDatum='EPSG:4269+5703',comparisonDatum='EPSG:4326+3855',
                oldTerrariumUsed=False,comparisonUsedToFillPrimary=False)


class Conversion:
    """Explicit reviewed operation; no ballpark, implicit grids, or datum relabeling."""
    def __init__(self, root, lock):
        self.lock=lock;self.grids={}
        for item in lock['grids']:
            path=Path(root)/'out/geography/input-cache'/item['filename']
            need(path.is_file() and path.stat().st_size==item['bytes'] and sha(path)==item['sha256'],
                 'Missing or changed conversion resource: '+item['filename'])
            self.grids[item['filename']]=path.resolve()
        operation=Path(root)/lock['operation']['path']
        need(sha(operation)==lock['operation']['sha256'],'Changed source datum operation')
        pyproj.network.set_network_enabled(False)
        pipeline=lock['operation']['pipeline']
        for name,path in self.grids.items():
            pipeline=pipeline.replace('grids='+name,'grids="'+path.as_posix()+'"')
        self.usgs=pyproj.Transformer.from_pipeline(pipeline)
        self.geoids={}
        for datum,name in [('EPSG:5773','us_nga_egm96_15.tif'),('EPSG:3855','us_nga_egm08_25.tif')]:
            pipeline=('+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad '
                      f'+step +proj=vgridshift +grids="{self.grids[name].as_posix()}" +multiplier=1 '
                      '+step +proj=unitconvert +xy_in=rad +xy_out=deg')
            self.geoids[datum]=pyproj.Transformer.from_pipeline(pipeline)

    def geoid(self, lon, lat, datum):
        need(datum in self.geoids,'Unknown or already-ellipsoidal height datum')
        lon,lat=np.broadcast_arrays(lon,lat)
        value=np.asarray(self.geoids[datum].transform(lon,lat,np.zeros(lon.shape),errcheck=True)[2])
        need(np.isfinite(value).all(),'Invalid geoid sample')
        return value

    def from_usgs(self, lon, lat, height, datum='EPSG:4269+5703'):
        need(datum=='EPSG:4269+5703','Unknown datum or duplicate source correction')
        result=self.usgs.transform(lon,lat,height,errcheck=True)
        need(all(np.isfinite(v).all() for v in result),'Nonfinite compound conversion')
        return result


def read_pixels(dataset, rows, columns):
    """Bounded native window; reject NoData even when a neighbour has zero weight."""
    rows=np.asarray(rows,dtype=np.int64);columns=np.asarray(columns,dtype=np.int64)
    need(rows.size>0 and rows.min()>=0 and rows.max()<dataset.height and
         columns.min()>=0 and columns.max()<dataset.width,'Missing raster interpolation boundary')
    r0,r1=int(rows.min()),int(rows.max())+1;c0,c1=int(columns.min()),int(columns.max())+1
    need((r1-r0)*(c1-c0)<=16_000_000,'Raster sample exceeds bounded window size')
    window=dataset.read(1,window=Window(c0,r0,c1-c0,r1-r0),masked=True)
    values=window[rows-r0,columns-c0]
    need(not np.ma.getmaskarray(values).any() and np.isfinite(values).all(),'NoData or invalid DEM pixels; no fallback')
    return np.asarray(values,dtype=float)


class RasterSet:
    def __init__(self, root, lock, dataset):
        self.kind=dataset;self.stack=ExitStack();self.datasets=[]
        rows=[r for r in lock['files'] if r['dataset']==dataset and r['kind']=='tif']
        # Explicit stable priority: western padded USGS cell, then eastern cell.
        rows.sort(key=lambda r:r['path'],reverse=True)
        try:
            self.stack.enter_context(rasterio.Env(GDAL_CACHEMAX=128*1024**2,PROJ_NETWORK='OFF'))
            for row in rows:
                ds=self.stack.enter_context(rasterio.open(Path(root)/row['path']))
                epsg=4269 if dataset=='usgs-3dep-13arcsec' else 4326
                need(ds.crs.to_epsg()==epsg and ds.count==1 and ds.dtypes==('float32',),'Unexpected native raster layout')
                expected=1/10800 if epsg==4269 else 1/3600
                need(abs(ds.res[0]-expected)<1e-12 and abs(ds.res[1]-expected)<1e-12,'Unexpected DEM post spacing')
                need(ds.transform.b==ds.transform.d==0 and ds.transform.e<0,'Unexpected raster orientation')
                self.datasets.append((row,ds))
            need(len(rows)==(2 if dataset=='usgs-3dep-13arcsec' else 6),'Incomplete raster set')
        except BaseException:
            self.close();raise

    def close(self):
        self.stack.close()

    def sample_usgs(self, lon, lat, only=None):
        lon,lat=np.broadcast_arrays(np.asarray(lon,dtype=float),np.asarray(lat,dtype=float))
        result=np.empty(lon.shape);assigned=np.zeros(lon.shape,dtype=bool)
        for record,ds in self.datasets:
            if only is not None and only not in record['path']:continue
            col=(lon-ds.transform.c)/ds.transform.a-.5;row=(lat-ds.transform.f)/ds.transform.e-.5
            x=np.floor(col).astype(np.int64);y=np.floor(row).astype(np.int64)
            mask=(~assigned)&(x>=0)&(x+1<ds.width)&(y>=0)&(y+1<ds.height)
            if not mask.any():continue
            xx,yy=x[mask],y[mask];dx,dy=col[mask]-xx,row[mask]-yy
            q00=read_pixels(ds,yy,xx);q10=read_pixels(ds,yy,xx+1)
            q01=read_pixels(ds,yy+1,xx);q11=read_pixels(ds,yy+1,xx+1)
            result[mask]=(q00*(1-dx)+q10*dx)*(1-dy)+(q01*(1-dx)+q11*dx)*dy
            assigned[mask]=True
        need(assigned.all(),'Incomplete USGS source coverage; no alternate-source fallback')
        return result

    def copernicus_pixels(self, x, y):
        result=np.empty(x.shape);assigned=np.zeros(x.shape,dtype=bool)
        for _,ds in self.datasets:
            west,north=ds.transform*(.5,.5)
            x0=int(round((west+180)*3600));y0=int(round((90-north)*3600))
            col,row=x-x0,y-y0
            mask=(~assigned)&(col>=0)&(col<ds.width)&(row>=0)&(row<ds.height)
            if not mask.any():continue
            result[mask]=read_pixels(ds,row[mask],col[mask]);assigned[mask]=True
        need(assigned.all(),'Missing Copernicus shared east/south posts')
        return result

    def sample_copernicus(self, lon, lat):
        lon,lat=np.broadcast_arrays(np.asarray(lon,dtype=float),np.asarray(lat,dtype=float))
        px=(lon+180)*3600;py=(90-lat)*3600
        # Exact geographic posts can otherwise move to an adjacent tile from ulp noise.
        px=np.where(abs(px-np.rint(px))<1e-7,np.rint(px),px)
        py=np.where(abs(py-np.rint(py))<1e-7,np.rint(py),py)
        x=np.floor(px).astype(np.int64);y=np.floor(py).astype(np.int64);dx,dy=px-x,py-y
        return ((self.copernicus_pixels(x,y)*(1-dx)+self.copernicus_pixels(x+1,y)*dx)*(1-dy)+
                (self.copernicus_pixels(x,y+1)*(1-dx)+self.copernicus_pixels(x+1,y+1)*dx)*dy)


class Primary:
    def __init__(self, root, config, lock):
        self.config=config;self.conversion=Conversion(root,lock);self.rasters=RasterSet(root,lock,'usgs-3dep-13arcsec')
        self.maximum_horizontal_residual=0.0;self.grid_boundary_samples=0

    def close(self):self.rasters.close()

    def sample(self, lon, lat, include_outer_posts=False):
        guard(self.config,lon,lat,include_outer_posts)
        lon,lat=np.broadcast_arrays(np.asarray(lon,dtype=float),np.asarray(lat,dtype=float))
        # Height-dependent horizontal Helmert terms are solved against the actual DEM.
        sx,sy,_=self.conversion.usgs.transform(lon,lat,np.zeros(lon.shape),direction='INVERSE',errcheck=True)
        best=np.full(lon.shape,np.inf);height=np.empty(lon.shape)
        for _ in range(4):
            native=self.rasters.sample_usgs(sx,sy)
            tx,ty,ellipsoid=self.conversion.from_usgs(sx,sy,native)
            # NADCON5 biquadratic stencil changes can have centimetre-scale jumps.
            # Keep the best evaluated point; record and bound its residual instead
            # of claiming an exact inverse across a discontinuity.
            residual=112000*np.hypot(np.asarray(tx)-lon,np.asarray(ty)-lat)
            better=residual<best;best=np.where(better,residual,best);height=np.where(better,ellipsoid,height)
            sx=sx+lon-tx;sy=sy+lat-ty
        need(float(best.max())<self.config['sourceHorizontalResidualLimitMeters'],
             'Compound source coordinate residual exceeds the fixed bound')
        self.maximum_horizontal_residual=max(self.maximum_horizontal_residual,float(best.max()))
        self.grid_boundary_samples+=int(np.count_nonzero(best>1e-5))
        return height-self.conversion.geoid(lon,lat,'EPSG:5773')


def derive_regional(root, output, config, lock):
    need(config['primarySource']=='usgs-3dep-13arcsec' and config['normalizedCRS']=='EPSG:4326+5773',
         'Unreviewed primary source or canonical datum')
    source=Primary(root,config,lock)
    b=config['bounds'];step=config['normalizedArcSeconds']/3600
    need(step==1/1200 and b==dict(west=-122,south=45,east=-120,north=46),'Unreviewed DTED grid')
    lon=np.linspace(-122,-120,2401);lat=np.linspace(46,45,1201)
    values=np.empty((1201,2401),dtype='<f4');ellipsoid=np.empty_like(values)
    try:
        for first in range(0,len(lat),32):
            lons,lats=np.meshgrid(lon,lat[first:first+32])
            values[first:first+32]=source.sample(lons,lats,include_outer_posts=True)
            ellipsoid[first:first+32]=values[first:first+32]+source.conversion.geoid(lons,lats,'EPSG:5773')
            if first%256==0:print(f'USGS normalized rows {first+len(lats)}/1201',flush=True)
        need(np.isfinite(values).all() and values.min()>=0 and values.max()<32767,
             'Invalid/negative primary terrain; current AMASE qualification refuses it')
        # Adjacent native USGS files overlap; sample both sides independently before accepting a mosaic.
        ys=np.linspace(45,46,1201);xs=np.full_like(ys,-121)
        west=source.rasters.sample_usgs(xs,ys,only='n46w122');east=source.rasters.sample_usgs(xs,ys,only='n46w121')
        delta=west-east
        need(np.max(abs(delta))<1,'USGS native overlap exceeds 1 m; source review required')
        save(output/'usgs-overlap.json',dict(samples=len(ys),longitude=-121,maximumDifferenceMeters=float(np.max(abs(delta))),
             nativeDatum='EPSG:4269+5703',blendingApplied=False))
        comparison=RasterSet(root,lock,'copernicus-glo30')
        try:
            xx,yy=np.meshgrid(np.arange(0,2401,30),np.arange(0,1201,30));lons=lon[xx];lats=lat[yy]
            other=comparison.sample_copernicus(lons,lats)+source.conversion.geoid(lons,lats,'EPSG:3855')-source.conversion.geoid(lons,lats,'EPSG:5773')
            differences=other-values[yy,xx];order=np.argsort(abs(differences).ravel())[-20:][::-1]
            save(output/'copernicus-comparison.json',dict(samples=int(other.size),comparisonDatum='EPSG:4326+5773',
                 medianDifferenceMeters=float(np.median(differences)),p95AbsoluteDifferenceMeters=float(np.percentile(abs(differences),95)),
                 maximumAbsoluteDifferenceMeters=float(np.max(abs(differences))),
                 largest=[dict(longitude=float(lons.flat[i]),latitude=float(lats.flat[i]),primaryMeters=float(values[yy,xx].flat[i]),
                               comparisonMeters=float(other.flat[i]),differenceMeters=float(differences.flat[i])) for i in order],
                 usedToFillPrimary=False,groundTruthClaimed=False,sourceIsDSM=True))
        finally:comparison.close()
        save(output/'source-coordinate-residual.json',dict(maximumBoundMeters=source.maximum_horizontal_residual,
             boundFormula='112000*hypot(deltaLongitudeDegrees,deltaLatitudeDegrees), conservative at this latitude',
             limitMeters=config['sourceHorizontalResidualLimitMeters'],samplesAboveTenMicrometres=source.grid_boundary_samples,
             method='Best of four evaluated iterations; NADCON5 biquadratic stencil boundaries may be discontinuous'))
    finally:source.close()
    transform=from_origin(-122-step/2,46+step/2,step,step)
    write_raster(output/'orthometric.tif',values,transform)
    ellipsoid.tofile(output/'cesium-heightfield.f32')
    dted=[]
    for x in range(2):
        folder=output/'dted'/('w'+str(122-x));folder.mkdir(parents=True)
        cell=np.rint(values[:,x*1200:x*1200+1201]).astype('int16')
        original=output/('dted-input-'+str(x)+'.tif')
        write_raster(original,cell,from_origin(-122+x-step/2,46+step/2,step,step))
        path=folder/'n45.dt1';raster_copy(original,path,driver='DTED')
        dted.append(dict(path=path.relative_to(output).as_posix(),sha256=sha(path),**validate_dted(path)))
    geod=pyproj.Geod(ellps='WGS84')
    result=dict(schemaVersion=2,regionId=config['regionId'],bounds=b,width=2401,height=1201,postStepDegrees=step,
        primarySource=config['primarySource'],comparisonSource=config['comparisonSource'],sourcePixelSpacingDegrees=1/10800,
        sourcePixelSpacingAtCenterMeters=dict(northSouth=geod.inv(-121,45.5,-121,45.5+1/10800)[2],eastWest=geod.inv(-121,45.5,-121+1/10800,45.5)[2]),
        normalizedGridSpacingMeters=dict(northSouth=geod.inv(-121,45.5,-121,45.5+step)[2],eastWest=geod.inv(-121,45.5,-121+step,45.5)[2]),
        orthometric=dict(path='orthometric.tif',datum='EPSG:5773',dtype='float32',minimum=float(values.min()),maximum=float(values.max())),
        cesium=dict(path='cesium-heightfield.f32',datum='EPSG:4979',dtype='float32-le',rowOrder='north-to-south',columnOrder='west-to-east'),
        vertical=dict(formula='USGS -> WGS84 ellipsoid -> H96; Cesium = canonical H96 + N96',appliedExactlyOnce=True,
                      projNetworkEnabled=False,operation=lock['operation'],grids=lock['grids'],
                      modelAccuracyMeters=2.1,numericalToleranceMeters=1,absoluteSurveyAccuracyClaimed=False),
        dted=dted,quantizationMaxErrorMeters=float(np.abs(np.rint(values)-values).max()),
        amaseConstraint='Nonnegative regional heights only; current formal reader negative/spacing limitations retained',
        coverageStatisticsGridMeters=20,absoluteSurveyAccuracyClaimed=False,oldTerrariumUsed=False)
    save(output/'terrain.json',result)
    return result
