"""Frozen public provenance, metadata spatial selection and strict raw DEM reads."""
import hashlib
import io
import json
import math
from pathlib import Path
import struct
from urllib.request import urlopen, Request
import zipfile

import numpy as np
from PIL import Image
from rasterio.features import rasterize
from rasterio.transform import from_bounds


def need(value,message):
    if not value: raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def fetch(item,folder):
    """Only a fixed HTTPS object may enter this task's derived input cache."""
    path=folder/item['filename'];folder.mkdir(parents=True,exist_ok=True)
    need(Path(item['filename']).name==item['filename'] and item['url'].startswith('https://'),'Invalid input lock')
    if not path.exists():
        temporary=path.with_suffix(path.suffix+'.download')
        with urlopen(item['url'],timeout=120) as response,temporary.open('wb') as target:
            need(response.url.startswith('https://'),'Insecure redirect')
            while block:=response.read(1024*1024):target.write(block)
            headers={k.lower():v for k,v in response.headers.items() if k.lower() in
                     ('content-length','last-modified','etag','x-amz-version-id','x-amz-meta-x-imagery-sources')}
        need(sha(temporary)==item['sha256'] and temporary.stat().st_size==item['bytes'],'Downloaded source differs')
        temporary.replace(path);save(folder/(item['filename']+'.http.json'),dict(url=item['url'],headers=headers))
    need(sha(path)==item['sha256'] and path.stat().st_size==item['bytes'],'Cached source differs')
    return path


def mercator_pixel(lon,lat,z):
    size=256*2**z
    return (np.asarray(lon)+180)/360*size-.5, (1-np.arcsinh(np.tan(np.radians(lat)))/np.pi)/2*size-.5


def tile_bounds(z,x,y):
    n=2**z
    def lat(row):return math.degrees(math.atan(math.sinh(math.pi*(1-2*row/n))))
    return (x/n*360-180,lat(y+1),(x+1)/n*360-180,lat(y))


def required_tiles(bounds,z):
    west,south,east,north=(bounds[k] for k in ('west','south','east','north'))
    x0,y0=mercator_pixel(west,north,z);x1,y1=mercator_pixel(east,south,z)
    return [(z,x,y) for x in range(math.floor(x0)//256,(math.floor(x1)+1)//256+1)
            for y in range(math.floor(y0)//256,(math.floor(y1)+1)//256+1)]


def decode_png(path):
    data=Path(path).read_bytes()
    need(data[:8]==b'\x89PNG\r\n\x1a\n' and len(data)>=33,'Invalid PNG signature')
    need(struct.unpack_from('>II',data,16)==(256,256) and data[24:26]==bytes([8,2]),'DEM must be 256x256 RGB8')
    # verify() validates every PNG chunk CRC; load() alone does not do this.
    try:
        with Image.open(io.BytesIO(data)) as image:image.verify()
        with Image.open(io.BytesIO(data)) as image:
            need(image.mode=='RGB','Unexpected DEM mode');rgb=np.asarray(image,dtype=np.float64)
    except (OSError,SyntaxError) as error:
        raise ValueError('Corrupt DEM PNG: '+str(path)) from error
    need(np.all(rgb[:,:,0]>0),'Terrarium no-data marker (red=0)')
    height=rgb[:,:,0]*256+rgb[:,:,1]+rgb[:,:,2]/256-32768
    need(np.isfinite(height).all() and height.min()>=-12000 and height.max()<=9000,'Invalid DEM elevation range')
    return height


def inventory_dem(root):
    """File names and coverage only globally; no claim to decode/hash all levels."""
    import os
    result=[]
    for z in range(11):
        directory=root/str(z);count=total=0
        with os.scandir(directory) as xs:columns=list(xs)
        need({p.name for p in columns}=={str(x) for x in range(2**z)},'DEM X coverage differs at '+str(z))
        for column in columns:
            need(column.is_dir(follow_symlinks=False),'Invalid DEM column')
            with os.scandir(column.path) as ys:rows=list(ys)
            need({p.name for p in rows}=={str(y)+'.png' for y in range(2**z)},'DEM Y coverage differs: '+column.path)
            for row in rows:
                need(row.is_file(follow_symlinks=False) and row.stat().st_size>=33,'Missing/empty DEM tile')
                count+=1;total+=row.stat().st_size
        result.append(dict(z=z,tiles=count,bytes=total,coverage='all expected XYZ filenames; decoding scope recorded separately'))
    return result


def provenance_tiles(root,lock,tiles):
    expected={tuple(row['xyz']):row for row in lock['demTiles']}
    need(set(expected)==set(tiles),'Frozen DEM source set differs from interpolation footprint')
    records=[];arrays={}
    for xyz in tiles:
        z,x,y=xyz;relative=f'tiles/dem/{z}/{x}/{y}.png';path=root/relative;row=expected[xyz]
        need(sha(path)==row['sha256'],'DEM digest differs: '+relative)
        need(row['sourceNames'] and all(name.startswith(('srtm/','gmted/')) for name in row['sourceNames']),
             'Unqualified contributing DEM source')
        arrays[xyz]=decode_png(path)
        records.append(dict(path=relative,sha256=row['sha256'],bytes=path.stat().st_size,
                            upstreamVersion=row['versionId'],sourceNames=row['sourceNames'],
                            minimum=float(arrays[xyz].min()),maximum=float(arrays[xyz].max())))
    return arrays,records


def spatial_metadata(archive,bounds,output):
    """Parse official SHP/DBF directly; keep only intersecting records, not 1.8 GB in RAM."""
    chosen={}
    with zipfile.ZipFile(archive) as z:
        prefix='GMTED2010_Spatial_Metadata/GMTED2010_Spatial_Metadata'
        projection=z.read(prefix+'.prj').decode('ascii')
        need('GCS_WGS_1984' in projection,'Unknown metadata horizontal datum')
        with z.open(prefix+'.shp') as stream:
            header=stream.read(100);need(struct.unpack_from('>I',header)[0]==9994,'Invalid SHP')
            while head:=stream.read(8):
                rid,words=struct.unpack('>2I',head);data=stream.read(words*2)
                need(len(data)==words*2 and struct.unpack_from('<I',data)[0]==5,'Unexpected/truncated metadata geometry')
                west,south,east,north=struct.unpack_from('<4d',data,4)
                if east<bounds[0] or west>bounds[2] or north<bounds[1] or south>bounds[3]:continue
                parts,count=struct.unpack_from('<2I',data,36)
                offsets=list(struct.unpack_from('<'+str(parts)+'I',data,44))+[count]
                points=list(struct.iter_unpack('<2d',data[44+parts*4:]))
                need(len(points)==count,'SHP point count differs')
                chosen[rid]=dict(record=rid,bbox=[west,south,east,north],
                                 rings=[points[a:b] for a,b in zip(offsets,offsets[1:])])
        with z.open(prefix+'.dbf') as stream:
            header=stream.read(32);count,header_size,row_size=struct.unpack_from('<IHH',header,4);fields=[]
            for _ in range((header_size-33)//32):
                field=stream.read(32);fields.append((field[:11].split(b'\0')[0].decode('ascii'),field[16]))
            need(stream.read(1)==b'\r','Invalid DBF header')
            for rid in range(1,count+1):
                data=stream.read(row_size);need(len(data)==row_size,'Truncated DBF')
                if rid not in chosen:continue
                need(data[:1]==b' ','Deleted source metadata');properties={};offset=1
                for name,length in fields:
                    properties[name]=data[offset:offset+length].decode('latin1').strip();offset+=length
                chosen[rid]['properties']=properties
    need(chosen,'No regional source metadata')
    for row in chosen.values():
        prop=row['properties']
        need(prop['VERT_DATUM']=='EGM96' and prop['VERT_UNIT']=='Meter' and prop['HORZ_DATUM']=='WGS 84'
             and prop['SOURCE']=='SRTM DTED2 Void Filled','Regional GMTED source/datum is not qualified')
        # The fixed region consists of complete, single-ring one-degree source
        # rectangles. Refuse more complex geometry instead of assuming its extent
        # proves coverage (holes or multiple source datums need a new qualification).
        ring=row['rings'];w,s,e,n=row['bbox']
        need(len(ring)==1 and len(ring[0])==5 and ring[0][0]==ring[0][-1], 'Complex provenance geometry requires review')
        corners={(round(x,8),round(y,8)) for x,y in ring[0]}
        need(corners=={(round(x,8),round(y,8)) for x in (w,e) for y in (s,n)},'Nonrectangular source footprint')
    # Exact partition check at every distinct source edge; tolerances only remove
    # round-off (~1e-13 degree) in the published vector coordinates.
    xs=sorted({bounds[0],bounds[2]}|{round(r['bbox'][i],8) for r in chosen.values() for i in (0,2)
                                  if bounds[0]<round(r['bbox'][i],8)<bounds[2]})
    ys=sorted({bounds[1],bounds[3]}|{round(r['bbox'][i],8) for r in chosen.values() for i in (1,3)
                                  if bounds[1]<round(r['bbox'][i],8)<bounds[3]})
    for x0,x1 in zip(xs,xs[1:]):
        for y0,y1 in zip(ys,ys[1:]):
            x,y=(x0+x1)/2,(y0+y1)/2
            need(any(w<=x<=e and s<=y<=n for w,s,e,n in (r['bbox'] for r in chosen.values())), 'Source metadata coverage gap')
    result=dict(bounds=bounds,projection=projection,verticalDatum='EPSG:5773',records=list(chosen.values()),
                coverage='continuous partition of source rectangles, including complete input tile footprints')
    save(output,result);return result
