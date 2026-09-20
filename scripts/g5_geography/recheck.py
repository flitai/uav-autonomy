"""Independent anomaly recheck: PNG filters/CRC, Pillow, GDAL, PROJ and optional HTTPS.

The USGS point service is diagnostic only, never a replacement elevation input.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
from urllib.request import urlopen
import warnings
import zlib

import numpy as np
from PIL import Image
import pyproj
import rasterio
from rasterio.errors import NotGeoreferencedWarning


def independent_rgb(data):
    if data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('PNG signature')
    cursor=8;compressed=bytearray();ended=False;width=height=0
    while cursor<len(data):
        if cursor+12>len(data):raise ValueError('Truncated PNG chunk')
        length=struct.unpack_from('>I',data,cursor)[0];kind=data[cursor+4:cursor+8]
        payload=data[cursor+8:cursor+8+length]
        if cursor+12+length>len(data) or zlib.crc32(kind+payload)!=struct.unpack_from('>I',data,cursor+8+length)[0]:
            raise ValueError('PNG CRC/length')
        if kind==b'IHDR':
            width,height=struct.unpack_from('>II',payload)
            if (width,height)!=(256,256) or payload[8:]!=bytes([8,2,0,0,0]):raise ValueError('Unsupported PNG layout')
        elif kind==b'IDAT':compressed.extend(payload)
        elif kind==b'IEND':ended=True
        cursor+=12+length
    if not ended or not width:raise ValueError('Incomplete PNG')
    raw=zlib.decompress(compressed);stride=width*3
    if len(raw)!=height*(stride+1):raise ValueError('Unexpected PNG raw size')
    decoded=bytearray(height*stride)
    for row in range(height):
        method=raw[row*(stride+1)]
        for column in range(stride):
            value=raw[row*(stride+1)+1+column]
            left=decoded[row*stride+column-3] if column>=3 else 0
            above=decoded[(row-1)*stride+column] if row else 0
            corner=decoded[(row-1)*stride+column-3] if row and column>=3 else 0
            if method==1:value+=left
            elif method==2:value+=above
            elif method==3:value+=(left+above)//2
            elif method==4:
                prediction=left+above-corner;pa,pb,pc=abs(prediction-left),abs(prediction-above),abs(prediction-corner)
                value+=left if pa<=pb and pa<=pc else above if pb<=pc else corner
            elif method!=0:raise ValueError('Unknown PNG filter')
            decoded[row*stride+column]=value&255
    return np.frombuffer(decoded,dtype=np.uint8).reshape(height,width,3)


def recheck(root,output,online=False):
    path=root/'tiles/dem/10/170/365.png';data=path.read_bytes();manual=independent_rgb(data)
    with Image.open(path) as image:np.testing.assert_array_equal(manual,np.asarray(image))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',NotGeoreferencedWarning)
        with rasterio.open(path) as dataset:np.testing.assert_array_equal(manual,np.moveaxis(dataset.read(),0,2))
    row,column=80,53;rgb=manual[row,column].tolist();height=rgb[0]*256+rgb[1]+rgb[2]/256-32768
    size=256*1024;radius=6378137
    x=((170*256+column+.5)/size*2-1)*math.pi*radius
    y=(1-(365*256+row+.5)/size*2)*math.pi*radius
    lon,lat=pyproj.Transformer.from_crs(3857,4326,always_xy=True).transform(x,y)
    result=dict(task='G5-T02',scope='anomaly diagnosis only',dataQualified=False,
        tile='10/170/365.png',pixelIndexOrigin=0,pixelColumn=column,pixelRow=row,rgb=rgb,heightMeters=height,
        longitude=lon,latitude=lat,formula=f'{rgb[0]} * 256 + {rgb[1]} + {rgb[2]} / 256 - 32768 = {height}',
        localSHA256=hashlib.sha256(data).hexdigest(),all65536PixelsIdentical=True,
        decoders=['standalone PNG filters+CRC','Pillow','GDAL Rasterio'],
        coordinateReference='PROJ EPSG:3857 to EPSG:4326 from XYZ pixel center',requests=[])
    if online:
        urls=['https://elevation-tiles-prod.s3.amazonaws.com/terrarium/10/170/365.png',
              'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/10/170/365.png?versionId=CdukG_DwFo6gY5O1ezTWHL1vEVcz8pil',
              f'https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Meters&wkid=4326&includeDate=true']
        for index,url in enumerate(urls):
            with urlopen(url,timeout=45) as response:
                body=response.read(1024*1024);headers={k.lower():v for k,v in response.headers.items()}
            entry=dict(url=url,bytes=len(body),sha256=hashlib.sha256(body).hexdigest(),
                       versionId=headers.get('x-amz-version-id'),sources=headers.get('x-amz-meta-x-imagery-sources'))
            if index<2:entry['sameAsLocal']=body==data
            else:entry.update(body=json.loads(body),diagnosticOnly=True,verticalDatumNotConverted=True)
            result['requests'].append(entry);(output/f'response-{index}.bin').write_bytes(body)
    (output/'recheck.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--online',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    print(json.dumps(recheck(args.root.resolve(),args.output,args.online),indent=2))
