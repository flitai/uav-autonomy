"""Independent native cell/report comparison and bounded reducer refusal checks."""
import argparse
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('coverage_engine_checks',ROOT/'scripts/g5_coverage/engine.py');e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)


def native(folder,snapshot):
    root=ET.parse(folder/'coverage-cells.xml').getroot();report=ET.parse(folder/'analysis.xml').find('SearchTaskAnalysis')
    assert float(root.get('GridResolutionMeters'))==20
    expected={t['taskId']:t for t in snapshot['tasks']};results=[]
    assert {n.get('ID') for n in root}==set(expected)
    for task in root:
        key=task.get('ID');value=expected[key];cells=task.findall('Cell')
        assert len(cells)==value['totalCells'];seen=[]
        for i,(cell,actual) in enumerate(zip(cells,value['cells'])):
            assert abs(float(cell.get('latitude'))-actual[0])<1e-10 and abs(float(cell.get('longitude'))-actual[1])<1e-10
            if cell.get('seen')=='true':seen.append(i)
        assert seen==value['seen'],(key,'native seen cells differ',len(set(seen)^set(value['seen'])))
        r=next(n for n in report if n.get('ID')==key)
        if value['kind']=='PointSearchTask':assert abs(float(r.findtext('TimeSeenSec'))-int(value['observationMilliseconds'])/1000)<=.0050001
        else:
            assert int(r.findtext('TotalCells'))==len(cells) and int(r.findtext('SeenCells'))==len(seen)
            assert abs(float(r.findtext('CoveragePercent'))-100*len(seen)/len(cells))<=.0050001
        results.append(dict(taskId=key,total=len(cells),seen=len(seen),observationMilliseconds=value['observationMilliseconds']))
    return dict(status='passed',nativeCellsCompared=sum(r['total'] for r in results),tasks=results)


def rendered(snapshot, objects, world):
    """Reconstruct which native cells actual Cesium rectangles/segments cover."""
    total=0
    for task in snapshot['tasks']:
        prefix='coverage:'+task['taskId']
        actual=[o for o in objects if o['id']==prefix or o['id'].startswith(prefix+':')]
        if task['kind']=='AreaSearchTask':
            grid=task['grid'];seen=set()
            lookup={(int(c[2]),int(c[3])):i for i,c in enumerate(task['cells'])}
            for obj in actual:
                west,south,east,north=map(math.degrees,obj['rectangle'])
                indices=[(west-grid['west'])/grid['dx'],(east-grid['west'])/grid['dx'],(grid['north']-north)/grid['dy'],(grid['north']-south)/grid['dy']]
                assert all(abs(v-round(v))<1e-6 for v in indices)
                x0,x1,y0,y1=map(round,indices);assert x1==x0+1 and y1>y0
                for y in range(y0,y1):
                    assert (x0,y) in lookup
                    i=lookup[x0,y];assert i not in seen;seen.add(i)
            assert seen==set(task['seen']),'Rendered area fills unobserved cells or omits observed ones'
        elif task['kind']=='LineSearchTask':
            edges=[(a,b) for obj in actual for a,b in zip(obj['positions'],obj['positions'][1:])]
            assert len(edges)==len(task['seen'])
            for (a,b),i in zip(edges,task['seen']):
                c=task['cells'][i]
                assert math.dist(a,world(c[1],c[0]))<1 and math.dist(b,world(c[3],c[2]))<1
        else:
            assert len(actual)==int(bool(task['seen']))
            if actual:
                c=task['cells'][0];assert math.dist(actual[0]['positions'][0],world(c[1],c[0]))<1
        total+=len(task['seen'])
    return dict(status='passed',actualCesiumSeenCellsCompared=total)


def unit(output,terrain):
    output.mkdir(parents=True);checks=[]
    def passed(name):checks.append(name)
    def reject(name,operation):
        try:operation()
        except (ValueError,AssertionError):passed(name)
        else:raise AssertionError('Expected refusal: '+name)
    point=lambda lat,lon:dict(Latitude=lat,Longitude=lon,Altitude=0,AltitudeType=1)
    definition=dict(_type='afrl.cmasi.PointSearchTask',TaskID='9223372036854775807',SearchLocation=point(45.3,-121),DwellTime='0',GroundSampleDistance=1000.,DesiredWavelengthBands=[0])
    task=e.Task(definition,50000)
    state=dict(ID='9223372036854775806',Time='9007199254740993',Location=point(45.3,-121))
    camera=dict(PayloadID='9223372036854775805',HorizontalFieldOfView=45.,Footprint=[point(45.29,-121.01),point(45.31,-121.01),point(45.31,-120.99),point(45.29,-120.99)])
    config=dict(VideoStreamHorizontalResolution=1024,SupportedWavelengthBand=1)
    task.observe(state,camera,config,1000);assert task.seen=={0};passed('large string IDs and source time')
    state['Time']=str(int(state['Time'])+500);task.observe(state,camera,config,1000);assert task.snapshot()['observationMilliseconds']=='500'
    task.observe(state,camera,config,1000);assert task.snapshot()['observationMilliseconds']=='500';passed('duplicate time does not add duration')
    state['Time']=str(int(state['Time'])+1001);task.observe(state,camera,config,1000);assert task.snapshot()['observationMilliseconds']=='500';passed('missing interval not counted')
    for name,change in [('band',{'DesiredWavelengthBands':[2]}),('GSD',{'GroundSampleDistance':.000001})]:
        t=e.Task(dict(definition,**change),50000);t.observe(state,camera,config,1000);assert not t.seen;passed(name+' refusal')
    t=e.Task(definition,50000);t.observe(state,dict(camera,Footprint=[]),config,1000);assert not t.seen;passed('empty footprint clears observation')
    t=e.Task(definition,50000);t.observe(state,dict(camera,Footprint=[point(44,-123),point(47,-123),point(47,-119),point(44,-119)]),config,1000);assert t.seen=={0};passed('outside planar corners classify qualified point without outside terrain')
    reject('nonzero dwell explicit refusal',lambda:e.Task(dict(definition,DwellTime='100'),50000))
    reject('cell budget refusal',lambda:e.Task(definition,0))
    reject('nonfinite coordinate refusal',lambda:e.point(point(float('nan'),-121)))
    native_terrain=e.Terrain(terrain);reject('no zero fallback',lambda:native_terrain.nearest(44,-121))
    reject('unknown state authority',lambda:e.Coverage('x',native_terrain).apply(dict(run_id='x',event_id=dict(shard='1',row_id='1'),message=dict(type='afrl.cmasi.SessionStatus',sourceEntity='1',sourceService='0',fields=dict(ScenarioTime='0')))))
    coverage=e.Coverage('x',native_terrain)
    reject('run mismatch',lambda:coverage.apply(dict(run_id='y')))
    reject('sequence gap',lambda:coverage.apply(dict(run_id='x',event_id=dict(shard='1',row_id='2'))))
    manifest=dict(run_id='x',processes=[],journal_anchors=[]);path=output/'corrupt.db3';db=sqlite3.connect(path)
    db.execute('create table metadata(id integer,binding text)');db.execute('insert into metadata values(1,?)',(json.dumps(manifest),));db.execute('create table events(shard integer,row_id integer,sha256 text,event text)');db.execute("insert into events values(1,1,'bad','{}')");db.commit();db.close()
    reject('corrupt journal refuses',lambda:e.read_batch(path,manifest,coverage))
    assert sqlite3.connect(path).execute('select count(*) from events').fetchone()[0]==1;passed('read-only ledger preserved')
    db=sqlite3.connect(path);db.execute('delete from events');db.commit();db.close()
    assert e.read_batch(path,manifest,coverage) is False;passed('new empty journal waits for first committed record')
    result=dict(status='passed',checks=checks);(output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--terrain',type=Path,required=True);a=p.parse_args();unit(a.output,a.terrain)
