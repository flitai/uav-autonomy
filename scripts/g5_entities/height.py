"""Extract exact EGM96 grid posts for the qualified region; independent PROJ references."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import pyproj

ROOT=Path(__file__).resolve().parents[2]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    lock=json.loads((ROOT/'config/g5-regional-sources.json').read_text(encoding='utf-8'));record=next(r for r in lock['grids'] if r['filename']=='us_nga_egm96_15.tif')
    path=ROOT/'out/geography/input-cache'/record['filename'];assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256']
    pyproj.network.set_network_enabled(False)
    transform=pyproj.Transformer.from_pipeline('+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=vgridshift +grids="'+path.as_posix()+'" +multiplier=1 +step +proj=unitconvert +xy_in=rad +xy_out=deg')
    ecef=pyproj.Transformer.from_crs('EPSG:4979','EPSG:4978',always_xy=True)
    values=[transform.transform(-122+x*.25,46-y*.25,0,errcheck=True)[2] for y in range(5) for x in range(9)]
    height=dict(west=-122,south=45,east=-120,north=46,width=9,height=5,stepDegrees=.25,values=values,datum='EGM96',sha256=record['sha256'])
    (args.output/'height.json').write_text(json.dumps(height,indent=2),encoding='utf-8')
    rng=random.Random(506);positions=[(-122,45,0),(-121,45.3,1090),(-121-1e-8,45.3,-100),(-121+1e-8,45.3,100),(-120-1e-8,46-1e-8,1090)]
    positions += [(-122+2*rng.random(),45+rng.random(),rng.uniform(-500,20000)) for _ in range(80)]
    references=[]
    for lon,lat,h in positions:
        correction=transform.transform(lon,lat,0,errcheck=True)[2];ellipsoid=h+correction
        references.append(dict(position=dict(longitude_deg=lon,latitude_deg=lat,altitude_m=h,altitude_reference=1),correction=correction,ellipsoid=ellipsoid,ecef=ecef.transform(lon,lat,ellipsoid,errcheck=True)))
    (args.output/'position-reference.json').write_text(json.dumps(references,indent=2),encoding='utf-8')
if __name__=='__main__':main()
