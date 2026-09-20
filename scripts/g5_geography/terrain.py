"""Regional, same-source orthometric/ellipsoid terrain derivation; never zero-fill."""
from collections import OrderedDict
import importlib.util
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

import numpy as np
import pyproj
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin

from sources import decode_png, mercator_pixel, need, save, sha


class Terrain:
    def __init__(self,root,config,tiles):
        self.root=Path(root);self.config=config;self.allowed={tuple(v) for v in tiles};self.cache=OrderedDict()

    def tile(self,x,y):
        key=(self.config['sourceZoom'],int(x),int(y))
        need(key in self.allowed,'Missing or unqualified interpolation tile')
        if key not in self.cache:
            self.cache[key]=decode_png(self.root/'tiles/dem'/str(key[0])/str(key[1])/(str(key[2])+'.png'))
            while len(self.cache)>self.config['demCacheTiles']:self.cache.popitem(last=False)
        self.cache.move_to_end(key);return self.cache[key]

    def pixel(self,x,y):
        x,y=np.broadcast_arrays(np.asarray(x,dtype=np.int64),np.asarray(y,dtype=np.int64));out=np.empty(x.shape)
        for tx,ty in set(zip((x//256).flat,(y//256).flat)):
            mask=(x//256==tx)&(y//256==ty)
            out[mask]=self.tile(tx,ty)[y[mask]%256,x[mask]%256]
        return out

    def sample(self,lon,lat,include_outer_posts=False):
        guard(self.config,lon,lat,include_outer_posts)
        px,py=mercator_pixel(lon,lat,self.config['sourceZoom']);x=np.floor(px).astype(np.int64);y=np.floor(py).astype(np.int64)
        dx,dy=px-x,py-y
        return (self.pixel(x,y)*(1-dx)+self.pixel(x+1,y)*dx)*(1-dy)+(self.pixel(x,y+1)*(1-dx)+self.pixel(x+1,y+1)*dx)*dy


def guard(config,lon,lat,include_outer_posts=False):
    b=config['bounds'];lon,lat=np.broadcast_arrays(lon,lat)
    inside=np.isfinite(lon)&np.isfinite(lat)&(lon>=b['west'])&(lat>=b['south'])
    inside &= ((lon<=b['east'])&(lat<=b['north'])) if include_outer_posts else ((lon<b['east'])&(lat<b['north']))
    need(np.all(inside),'Coordinate outside qualified region; no zero-height fallback')


class VerticalTransform:
    def __init__(self,grid,expected_hash):
        grid=Path(grid).resolve();need(grid.is_file() and sha(grid)==expected_hash,'Missing or changed geoid grid')
        pyproj.network.set_network_enabled(False)
        self.pipeline=('+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad '
                       f'+step +proj=vgridshift +grids="{grid.as_posix()}" +multiplier=1 '
                       '+step +proj=unitconvert +xy_in=rad +xy_out=deg')
        self.transform=pyproj.Transformer.from_pipeline(self.pipeline)

    def ellipsoid(self,lon,lat,height,source_datum):
        need(source_datum=='EPSG:5773','Unknown datum or duplicate vertical correction')
        result=self.transform.transform(lon,lat,height,errcheck=True)[2]
        need(np.isfinite(result).all(),'Non-finite vertical conversion')
        return result


def scene_extent(root,output,config):
    spec=importlib.util.spec_from_file_location('g5_g4_scene',root/'scripts/g4_mixed/scene.py')
    scene=importlib.util.module_from_spec(spec);spec.loader.exec_module(scene)
    scene.build(root,output/'mixed20', ['line']*8+['point']*6+['area']*6,[400,500]+list(range(600,618)))
    paths=[root/scene.INPUTS['scenario'],root/scene.INPUTS['line']]+list((output/'mixed20').glob('*.xml'))
    points=[];geod=pyproj.Geod(ellps='WGS84')
    for path in paths:
        node=ET.parse(path).getroot()
        for p in node.iter():
            lat,lon=p.findtext('Latitude'),p.findtext('Longitude')
            if lat is not None and lon is not None:points.append((float(lon),float(lat)))
        for rect in node.iter('Rectangle'):
            c=rect.find('CenterPoint/Location3D');lon=float(c.findtext('Longitude'));lat=float(c.findtext('Latitude'))
            dx,dy=float(rect.findtext('Width'))/2,float(rect.findtext('Height'))/2
            angle=float(rect.findtext('Rotation'))
            for x,y in ((-dx,-dy),(-dx,dy),(dx,-dy),(dx,dy)):
                east,north=geod.fwd(lon,lat,math.degrees(math.atan2(x,y))+angle,math.hypot(x,y))[:2];points.append((east,north))
    need(points,'Empty scenario domain')
    # Geodesic circles about all authored positions and task vertices. A global
    # rectangular envelope covers their connecting segments in this small region.
    buffered=list(points)
    for lon,lat in points:
        for azimuth in range(0,360,5):buffered.append(geod.fwd(lon,lat,azimuth,config['scenarioBufferMeters'])[:2])
    xs,ys=zip(*buffered);bound=dict(west=min(xs),south=min(ys),east=max(xs),north=max(ys))
    guard(config,[bound['west'],bound['east']],[bound['south'],bound['north']])
    record=dict(authoredPoints=len(points),scenarioBounds=dict(west=min(p[0] for p in points),south=min(p[1] for p in points),
        east=max(p[0] for p in points),north=max(p[1] for p in points)),bufferMeters=config['scenarioBufferMeters'],
        bufferedBounds=bound,qualifiedStorageBounds=config['bounds'],
        flightRule='T04 must continuously reject planned or actual flight outside the qualified region; authored geometry is not a prediction of flight',
        sources=[dict(path=str(p.relative_to(root)).replace('\\','/'),sha256=sha(p)) for p in
                 [root/v for v in scene.INPUTS.values()]+[root/'scripts/g4_mixed/scene.py']])
    save(output/'scene-domain.json',record);return record


def write_raster(path,grid,transform):
    with rasterio.open(path,'w',driver='GTiff',height=grid.shape[0],width=grid.shape[1],count=1,
                       dtype=grid.dtype,crs='EPSG:4326+5773',transform=transform,compress='DEFLATE',
                       tiled=True,blockxsize=256,blockysize=256) as dataset:
        dataset.write(grid,1);dataset.update_tags(AREA_OR_POINT='Point',VERTICAL_DATUM='EGM96',UNITTYPE='metre')


def validate_dted(path,nonnegative=True):
    """Strict signed-magnitude and checksum validation before AMASE consumption."""
    data=Path(path).read_bytes();need(data[:4]==b'UHL1' and data[80:83]==b'DSI' and data[728:731]==b'ACC','Invalid DTED headers')
    nx,ny=int(data[47:51]),int(data[51:55]);need(nx==ny==1201,'Not a qualified DTED Level 1 cell')
    need(data[20:28]==b'00300030','Unexpected DTED spacing')
    length=12+2*ny;need(len(data)==3428+nx*length,'Truncated/extra DTED bytes');low=32767;high=-32767
    for x in range(nx):
        block=data[3428+x*length:3428+(x+1)*length]
        need(block[0]==170 and int.from_bytes(block[1:4],'big')==x and int.from_bytes(block[4:6],'big')==x
             and block[6:8]==b'\0\0','Invalid DTED column identity')
        need(sum(block[:-4])==int.from_bytes(block[-4:],'big'),'DTED checksum differs')
        encoded=np.frombuffer(block[8:-4],dtype='>u2');magnitudes=(encoded&32767).astype(np.int32)
        values=np.where(encoded&32768,-magnitudes,magnitudes)
        need(not np.any(values==-32767),'DTED no-data refused')
        if nonnegative:need(np.all(values>=0),'Negative DTED unsupported by current formal AMASE reader')
        low=min(low,int(values.min()));high=max(high,int(values.max()))
    return dict(width=nx,height=ny,minimum=low,maximum=high,allColumnChecksumsVerified=True,signedMagnitude=True)


def derive(root,output,config,tiles,grid,grid_hash):
    source=Terrain(root,config,tiles);vertical=VerticalTransform(grid,grid_hash);b=config['bounds'];step=config['normalizedArcSeconds']/3600
    need(step==1/1200 and (b['west'],b['south'],b['east'],b['north'])==(-122,45,-120,46), 'Unreviewed DTED region/grid')
    lon=np.linspace(b['west'],b['east'],2401);lat=np.linspace(b['north'],b['south'],1201)
    values=np.empty((1201,2401),dtype=np.float64);ellipsoid=np.empty_like(values,dtype='<f4')
    for first in range(0,len(lat),32):
        lons,lats=np.meshgrid(lon,lat[first:first+32]);h=source.sample(lons,lats,include_outer_posts=True)
        values[first:first+32]=h
        ellipsoid[first:first+32]=vertical.ellipsoid(lons,lats,h,'EPSG:5773')
    suspicious=np.argwhere(values<0)
    if len(suspicious):
        save(output/'terrain-rejection.json',dict(status='rejected',reason='Negative regional DEM values require source review; current AMASE cannot consume them',
            minimum=float(values.min()),maximum=float(values.max()),negativePosts=len(suspicious),
            samples=[dict(row=int(y),column=int(x),longitude=float(lon[x]),latitude=float(lat[y]),orthometricMeters=float(values[y,x]))
                     for y,x in suspicious],automaticFillApplied=False,regionalTerrainQualified=False))
    need(values.min()>=0 and values.max()<32767,'Regional terrain rejected; inspect terrain-rejection.json (no clamping or zero fill)')
    transform=from_origin(b['west']-step/2,b['north']+step/2,step,step)
    write_raster(output/'orthometric.tif',values.astype('float32'),transform)
    ellipsoid.tofile(output/'cesium-heightfield.f32')
    dted=[]
    for x in range(2):
        column=int(b['west'])+x;folder=output/'dted'/('w'+str(abs(column)).zfill(3));folder.mkdir(parents=True)
        cell=np.rint(values[:,x*1200:x*1200+1201]).astype('int16')
        original=output/('dted-input-'+str(x)+'.tif')
        write_raster(original,cell,from_origin(column-step/2,b['north']+step/2,step,step))
        path=folder/'n45.dt1';raster_copy(original,path,driver='DTED')
        dted.append(dict(path=path.relative_to(output).as_posix(),sha256=sha(path),**validate_dted(path)))
    # Shared boundary equality is exact because both cells are slices of one grid.
    result=dict(schemaVersion=1,regionId=config['regionId'],bounds=b,width=2401,height=1201,postStepDegrees=step,
        sourceZoom=config['sourceZoom'],sourcePixelSpacingAtCenterMeters=2*math.pi*6378137*math.cos(math.radians(45.5))/(256*2**10),
        normalizedGridSpacingMeters=dict(northSouth=pyproj.Geod(ellps='WGS84').inv(-121,45.5,-121,45.5+step)[2],
                                          eastWest=pyproj.Geod(ellps='WGS84').inv(-121,45.5,-121+step,45.5)[2]),
        orthometric=dict(path='orthometric.tif',datum='EPSG:5773',dtype='float32',minimum=float(values.min()),maximum=float(values.max())),
        cesium=dict(path='cesium-heightfield.f32',datum='EPSG:4979',dtype='float32-le',rowOrder='north-to-south',columnOrder='west-to-east'),
        vertical=dict(grid=grid.name,sha256=grid_hash,formula='h=H+N',appliedExactlyOnce=True,projNetworkEnabled=False,
                      pipelineTemplate=vertical.pipeline.replace(grid.resolve().as_posix(),'<qualified-geoid-grid>')),
        dted=dted,quantizationMaxErrorMeters=float(np.abs(np.rint(values)-values).max()),
        amaseConstraint='Nonnegative regional heights only; signed-magnitude negative values refused by qualification guard',
        coverageStatisticsGridMeters=20,absoluteSurveyAccuracyClaimed=False)
    save(output/'terrain.json',result);return result
