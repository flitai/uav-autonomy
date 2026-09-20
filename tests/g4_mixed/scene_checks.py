"""Verify generated small scenarios against original geometry and CMASI bytes."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback
from xml.dom import minidom
import xml.etree.ElementTree as ET


def verify(root, output):
    sys.path.insert(0,str(root/'src'))
    from sim_bridge.codec import Decoder, load_schema
    schema=load_schema(root); decoder=Decoder(schema)
    from lmcp.LMCPFactory import packMessage
    spec=importlib.util.spec_from_file_location('mixed_scene',root/'scripts/g4_mixed/scene.py')
    scene=importlib.util.module_from_spec(spec); spec.loader.exec_module(scene)
    result=[]
    for name,kinds,ids in [('point',['point'],['400']),('line',['line'],['400']),('area',['area'],['400']),
                           ('mixed',['line','point','area'],['400','500','600'])]:
        directory=output/name; manifest=scene.build(root,directory,kinds,ids)
        original=ET.parse(root/scene.INPUTS['scenario']).getroot()
        generated=ET.parse(directory/'scenario.xml').getroot()
        events=generated.findall('ScenarioEventList/*'); assert len(events)==3*len(ids)
        assert generated.findtext('ScenarioData/ScenarioDuration')=='1800.0'
        decoded=0
        for row in manifest['assignments']:
            entity,task_id=row['entityId'],row['taskId']; base=row['sourceEntityId']
            for tag,field in [('AirVehicleConfiguration','ID'),('AirVehicleState','ID'),('MissionCommand','VehicleID')]:
                nodes=[n for n in events if n.tag==tag and n.findtext(field)==entity]; assert len(nodes)==1
                origin=next(n for n in original.findall('ScenarioEventList/'+tag) if n.findtext(field)==base)
                for axis,offset in [('Latitude',row['latitudeOffsetDegrees']),('Longitude',row['longitudeOffsetDegrees'])]:
                    a,b=list(origin.iter(axis)),list(nodes[0].iter(axis)); assert len(a)==len(b)
                    assert all(abs(float(y.text)-float(x.text)-offset)<1e-10 for x,y in zip(a,b))
            task=ET.parse(directory/row['taskFile']).getroot(); request=ET.parse(directory/row['requestFile']).getroot()
            assert task.findtext('TaskID')==task_id and task.findtext('EligibleEntities/int64')==entity
            assert request.findtext('EntityList/int64')==entity and len(request.findall('EntityList/int64'))==1
            assert request.findtext('TaskList/int64')==task_id and request.findtext('RedoAllTasks')=='false'
            assert task.findtext('DesiredWavelengthBands/WavelengthBand')=='AllAny' and task.findtext('DwellTime')=='0'
            assert task.findtext('GroundSampleDistance')=='1000'
            if row['kind']=='line':
                waterway=ET.parse(root/scene.INPUTS['line']).getroot().findall('PointList/Location3D')
                points=task.findall('PointList/Location3D'); assert len(points)==len(waterway)==90
                for axis,offset in [('Latitude',row['latitudeOffsetDegrees']),('Longitude',row['longitudeOffsetDegrees'])]:
                    assert all(abs(float(b.findtext(axis))-float(a.findtext(axis))-offset)<1e-10 for a,b in zip(waterway,points))
            if row['kind']=='area':
                assert task.findtext('SearchArea/Rectangle/Width')=='1000' and task.findtext('SearchArea/Rectangle/Height')=='500'
            for node in [task,request]:
                with minidom.parseString(ET.tostring(node,encoding='unicode')) as xml:
                    obj=schema.factory.createObjectByName(node.get('Series'),node.tag)
                    obj.unpackFromXMLNode(xml.documentElement,schema.factory)
                data=bytes(packMessage(obj,True)); descriptor=obj.FULL_LMCP_TYPE_NAME
                decoded_message=decoder.decode({'body':(descriptor+'$lmcp|'+descriptor+'||100|1$').encode('ascii')+data})
                assert decoded_message.metadata()['type']==descriptor; decoded+=1
        result.append({'case':name,'entities':ids,'taskKinds':kinds,'strictlyDecodedTaskAndRequestMessages':decoded,'status':'passed'})
    return result


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    root=parser.parse_args().root.resolve()
    run_id='g4-t07-scenes-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output=root/'out/runs'/run_id; output.mkdir()
    sources=[root/'scripts/g4_mixed/scene.py',Path(__file__).resolve()]
    record={'status':'running','runId':run_id,'scope':'generated-inputs-only',
            'sources':[{'path':p.relative_to(root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources]}
    try: record.update(status='passed',cases=verify(root,output)); return 0
    except Exception as error: record.update(status='failed',error=str(error),traceback=traceback.format_exc()); return 1
    finally:
        (output/'result.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record,indent=2),flush=True)


if __name__=='__main__': sys.exit(main())
