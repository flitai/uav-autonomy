"""T02 Python decoder generates independent real MVT and terrain reference cases."""
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g5_geography'))
from pmtiles import Archive,inspect_mvt


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    config=json.loads((ROOT/'config/g5-map.json').read_text());candidate=ROOT/'out/geography'/config['geographyBuildRunId']
    archive=Archive(ROOT/'tiles/tiles/planet.pmtiles');rows=[]
    try:
        for index,(z,lon,lat) in enumerate([(0,0,0),(5,-121,45.3),(10,-121,45.3),(15,-121,45.3),
                (5,116.397,39.908),(10,116.397,39.908),(15,116.397,39.908),(15,-140,0)]):
            x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
            data,info=archive.tile(z,x,y);name=f'tile-{index}.mvt';(output/name).write_bytes(data)
            details=inspect_mvt(data) if data else {'layers':[]}
            rows.append(dict(file=name,xyz=[z,x,y],tileId=info['tileId'],layers=details['layers']))
    finally:archive.close()
    grid=json.loads((candidate/'terrain.json').read_text());field=np.fromfile(candidate/'cesium-heightfield.f32',dtype='<f4').reshape(grid['height'],grid['width'])
    # Independent barycentric solve (not the production piecewise formula).
    samples=[]
    for gx,gy in [(0,0),(2400,0),(0,1200),(2400,1200),(331,425),(801.2,503.3),(1655.8,648.7),(1200,510.5)]:
        x=min(int(gx),grid['width']-2);y=min(int(gy),grid['height']-2);u=gx-x;v=gy-y
        vertices=[(0,0),(1,0),(0,1)] if u+v<=1 else [(1,1),(1,0),(0,1)]
        matrix=np.array([[a,b,1] for a,b in vertices]).T;weights=np.linalg.solve(matrix,np.array([u,v,1]))
        expected=float(sum(weights[i]*float(field[y+b,x+a]) for i,(a,b) in enumerate(vertices)))
        samples.append(dict(longitude=-122+gx/1200,latitude=46-gy/1200,expected=expected))
    (output/'reference.json').write_text(json.dumps(dict(mvt=rows,terrain=samples,heightfield=str(candidate/'cesium-heightfield.f32'),grid=grid),indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main(Path(sys.argv[1]))
