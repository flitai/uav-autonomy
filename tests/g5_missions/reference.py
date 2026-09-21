"""Independent stdlib spherical CMASI corners, WGS84 Cartesian and bilinear oracle."""
import array
import importlib.util
import json
import math
from pathlib import Path
import random
import sys

def load(path):return json.loads(path.read_text(encoding='utf-8'))
def bilinear(lon,lat,g,values):
    col=(lon-g['west'])/g['stepDegrees'];row=(g['north']-lat)/g['stepDegrees']
    x=min(g['width']-2,int(col));y=min(g['height']-2,int(row));fx=col-x;fy=row-y
    return sum(values[(y+dy)*g['width']+x+dx]*wx*wy for dx,wx in [(0,1-fx),(1,fx)] for dy,wy in [(0,1-fy),(1,fy)])
def ecef(lon,lat,h):
    lon,lat=map(math.radians,(lon,lat));f=1/298.257223563;e2=f*(2-f);n=6378137/math.sqrt(1-e2*math.sin(lat)**2)
    return [(n+h)*math.cos(lat)*math.cos(lon),(n+h)*math.cos(lat)*math.sin(lon),(n*(1-e2)+h)*math.sin(lat)]
def corners(center,width,height,rotation):
    # Resolve local corner bearings from AMASE's north/east width/height convention.
    lon,lat=map(math.radians,center);result=[]
    for east,north in [(-width/2,height/2),(width/2,height/2),(width/2,-height/2),(-width/2,-height/2)]:
        bearing=math.atan2(east,north)+math.radians(rotation);arc=math.hypot(east,north)/6378137
        p=math.asin(math.sin(lat)*math.cos(arc)+math.cos(lat)*math.sin(arc)*math.cos(bearing))
        l=lon+math.atan2(math.sin(bearing)*math.sin(arc)*math.cos(lat),math.cos(arc)-math.sin(lat)*math.sin(p))
        result.append([math.degrees(l),math.degrees(p)])
    return result
def main(project,output):
    spec=importlib.util.spec_from_file_location('mission_fixtures',Path(__file__).with_name('fixtures.py'));f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
    cfg=load(project/'public/missions/runtime.json');g=cfg['ground'];geoid=load(project/'public/entities/runtime.json')['height']
    values=array.array('f');values.frombytes((project/'public/missions/orthometric.f32').read_bytes());assert sys.byteorder=='little'
    rng=random.Random(703);coords=[(-121,45),(-121,45.3),(-121-1/2400,45.3),(-121+1/2400,45.3)]+[(rng.uniform(-121.95,-120.05),rng.uniform(45.01,45.99)) for _ in range(1000)]
    samples=[]
    for i,(lon,lat) in enumerate(coords):
        ground=bilinear(lon,lat,g,values);n=bilinear(lon,lat,geoid,geoid['values']);height=100 if i%2 else 1100;ref=i%2;msl=height+(ground if ref==0 else 0)
        samples.append(dict(longitude=lon,latitude=lat,altitude=height,reference=ref,ground=ground,msl=msl,ellipsoid=msl+n,ecef=ecef(lon,lat,msl+n)))
    result=dict(scope='independent numerical and protocol examples',samples=samples,rectangles=[dict(rotation=r,corners=corners((-120.7,45.3),1000,500,r)) for r in (0,90,33)],fixture=f.state())
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
