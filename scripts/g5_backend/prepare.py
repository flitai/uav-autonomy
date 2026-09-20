"""Freeze terrain scene copies using the qualified canonical orthometric grid.

Run only in the locked G5 geography interpreter. No source files are modified.
"""
import argparse
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('backend_prepare_common', Path(__file__).with_name('common.py'))
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
scenes = c.module('backend_original_mixed_scenes', ROOT / 'scripts/g4_mixed/scene.py')

def points(node):
    return [(float(n.findtext('Longitude')), float(n.findtext('Latitude')))
            for n in node.iter() if n.find('Longitude') is not None and n.find('Latitude') is not None]

def sample(grid, lon, lat):
    c.need(-122 <= lon < -120 and 45 <= lat < 46, 'Ground task outside qualified region')
    x, y = (lon + 122) * 1200, (46 - lat) * 1200
    i, j = math.floor(x), math.floor(y)
    dx, dy = x-i, y-j
    return ((float(grid[j,i])*(1-dx)+float(grid[j,i+1])*dx)*(1-dy)
            +(float(grid[j+1,i])*(1-dx)+float(grid[j+1,i+1])*dx)*dy)

def original(root, directory):
    directory.mkdir()
    for source, name in [(scenes.INPUTS['scenario'], 'scenario.xml'), (scenes.INPUTS['line'], 'task-1000.xml'),
        ('OpenUxAS/examples/02_Example_WaterwaySearch/MessagesToSend/tasks/1001_AutomationRequest_LINE_Waterway_Deschutes.xml', 'request-1000.xml')]:
        shutil.copy2(root / source, directory / name)
    return dict(schemaVersion=1, purpose='original-two-entity-terrain-copy', assignments=[
        dict(entityId=e, taskId='1000', kind='line', taskFile='task-1000.xml', requestFile='request-1000.xml') for e in ('400','500')])

def build(root, geography, output):
    config = c.load(root / 'config/g5-backend-terrain.json')
    output.mkdir(parents=True, exist_ok=False)
    with rasterio.open(geography / 'orthometric.tif') as dataset:
        grid = dataset.read(1)
    c.need(grid.shape == (1201,2401) and np.isfinite(grid).all() and grid.min() >= 0, 'Canonical grid invalid')
    grid.astype('<f4').tofile(output / 'orthometric.f32')
    shutil.copytree(geography / 'dted', output / 'dted')
    raw = output / 'unadapted'; raw.mkdir()
    ids = ['400','500'] + [str(i) for i in range(600,618)]
    manifests = {'original': original(root, raw/'original'),
        'small': scenes.build(root, raw/'small', config['smallKinds'], config['smallEntityIds']),
        'mixed20': scenes.build(root, raw/'mixed20', ['line']*8+['point']*6+['area']*6, ids)}
    all_points, flying = [], []
    for name in manifests:
        for path in (raw/name).glob('*.xml'):
            node = ET.parse(path).getroot(); all_points += points(node)
            if path.name == 'scenario.xml':
                flying += [float(v.text) for v in node.iter() if v.tag in ('Altitude','NominalAltitude')]
    # Rectangle half-diagonal (559 m) is included before the prescribed 5 km buffer.
    # The same conservative full Mixed20 envelope freezes heights for all copies.
    margin = config['scenarioBufferMeters'] + math.hypot(1000/2,500/2)
    north = max(p[1] for p in all_points) + math.degrees(margin/6378137)
    south = min(p[1] for p in all_points) - math.degrees(margin/6378137)
    east = max(p[0] for p in all_points) + math.degrees(margin/(6378137*math.cos(math.radians(north))))
    west = min(p[0] for p in all_points) - math.degrees(margin/(6378137*math.cos(math.radians(north))))
    c.need(-122 < west < east < -120 and 45 < south < north < 46, 'Buffered scene outside terrain')
    left, right = math.floor((west+122)*1200), math.ceil((east+122)*1200)
    top, bottom = math.floor((46-north)*1200), math.ceil((46-south)*1200)
    cell = grid[top:bottom+1,left:right+1]
    maximum = max(float(cell.max()), float(np.rint(cell).max()))
    lift = max(0, math.ceil(maximum + config['minimumClearanceMeters'] - min(flying)))
    differences = []
    for name, manifest in manifests.items():
        target = output/name; shutil.copytree(raw/name, target)
        for path in target.glob('*.xml'):
            node = ET.parse(path).getroot()
            for index, n in enumerate(node.iter()):
                if path.name == 'scenario.xml' and n.tag in ('Altitude','NominalAltitude'):
                    before = n.text; n.text = format(float(before)+lift, '.12g')
                    differences.append(dict(scene=name,file=path.name,index=index,field=n.tag,before=before,after=n.text,rule='uniform-flight-lift'))
                elif path.name.startswith('task-') and n.find('Latitude') is not None and n.find('Longitude') is not None:
                    old = n.find('Altitude'); before = old.text if old is not None else None
                    value = sample(grid,float(n.findtext('Longitude')),float(n.findtext('Latitude')))
                    scenes.set_text(n,'Altitude',format(value,'.12g')); scenes.set_text(n,'AltitudeType','MSL')
                    differences.append(dict(scene=name,file=path.name,index=index,field='Altitude',before=before,after=n.findtext('Altitude'),rule='canonical-bilinear-H96'))
            if path.name == 'scenario.xml':
                scenes.set_text(node.find('ScenarioData'),'ScenarioName','G5 terrain '+name)
            scenes.write(node,path)
        manifest.update(terrainScenario=True,sceneId='g5-terrain-'+name+'-usgs-egm96-v1',heightDatum='EPSG:5773',uniformFlightLiftMeters=lift)
        manifest['files'] = c.base.inventory(target, sorted(target.glob('*.xml')))
        c.save(target/'scene.json',manifest)
    adaptation = dict(schemaVersion=1,regionId=c.load(geography/'terrain.json')['regionId'],
        bounds=dict(west=west,south=south,east=east,north=north),bufferMeters=config['scenarioBufferMeters'],
        rectangleEnvelopeAllowanceMeters=math.hypot(500,250),postWindow=dict(left=left,right=right,top=top,bottom=bottom),
        maximumCanonicalMeters=float(cell.max()),maximumQuantizedMeters=float(np.rint(cell).max()),
        minimumOriginalFlightMeters=min(flying),uniformFlightLiftMeters=lift,
        minimumAdaptedFlightMeters=min(flying)+lift,minimumClearanceMeters=min(flying)+lift-maximum,
        horizontalGeometryChanged=False,coverageParametersChanged=False,differences=differences)
    c.save(output/'adaptation.json',adaptation)
    return adaptation

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--geography',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=build(ROOT,args.geography,args.output)
    print('Frozen lift='+str(result['uniformFlightLiftMeters'])+' m; minimum clearance='+str(result['minimumClearanceMeters'])+' m',flush=True)
