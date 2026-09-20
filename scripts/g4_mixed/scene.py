"""Deterministic CMASI test scenes; original inputs are always kept unchanged."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


INPUTS = {
    'scenario': 'OpenUxAS/examples/02_Example_WaterwaySearch/Scenario_WaterwaySearch.xml',
    'line': 'OpenUxAS/examples/02_Example_WaterwaySearch/MessagesToSend/tasks/1000_LineSearch_LINE_Waterway_Deschutes.xml',
    'point': 'OpenUxAS/examples/99_Tasks/CmasiPointSearchTask/MessagesToSend/PointSearchTask_100.xml',
    'area': 'OpenUxAS/examples/99_Tasks/CmasiAreaSearchTask/Rectangle/MessagesToSend/AreaSearchTask_100.xml',
}
ANCHOR = (45.323, -120.9645)
GRID = (.15, .20)


def set_text(node, name, value):
    child = node.find(name)
    if child is None: child = ET.SubElement(node, name)
    child.text = str(value)


def translate(node, latitude, longitude):
    for value in node.iter('Latitude'): value.text = format(float(value.text) + latitude, '.15g')
    for value in node.iter('Longitude'): value.text = format(float(value.text) + longitude, '.15g')


def write(node, path):
    ET.indent(node, space='  ')
    ET.ElementTree(node).write(path, encoding='utf-8', xml_declaration=True)


def build(root, directory, kinds, ids, duration=1800):
    root, directory = Path(root), Path(directory)
    if len(kinds) != len(ids) or len(set(ids)) != len(ids) or not 1 <= len(ids) <= 20:
        raise ValueError('Each distinct real entity needs exactly one task')
    if any(kind not in ('point','line','area') for kind in kinds): raise ValueError('Unsupported task')
    directory.mkdir(parents=True, exist_ok=False)
    source = {key: ET.parse(root / path).getroot() for key,path in INPUTS.items()}
    scenario = deepcopy(source['scenario']); events = scenario.find('ScenarioEventList'); events.clear()
    set_text(scenario.find('ScenarioData'), 'ScenarioName', 'G4 fixed mixed-task qualification')
    set_text(scenario.find('ScenarioData'), 'ScenarioDuration', float(duration))
    templates = source['scenario'].find('ScenarioEventList')
    manifest = {'schemaVersion':1, 'purpose':'functional-test-scene', 'simulationRate':1,
                'durationSeconds':duration, 'gridDegrees':{'latitude':GRID[0],'longitude':GRID[1]},
                'gridColumns':5, 'rectangleMeters':{'width':1000,'height':500}, 'assignments':[],
                'inputs':[{'path':p,'sha256':hashlib.sha256((root/p).read_bytes()).hexdigest()} for p in INPUTS.values()]}
    for index,(kind,entity) in enumerate(zip(kinds,ids)):
        entity=str(entity); base='500' if entity=='500' else '400'
        dlat,dlon=GRID[0]*(index//5),GRID[1]*(index%5)
        for tag,id_field,at in [('AirVehicleConfiguration','ID',1),('AirVehicleState','ID',1.4),('MissionCommand','VehicleID',1.8)]:
            original=next(n for n in templates.findall(tag) if n.findtext(id_field)==base)
            node=deepcopy(original); set_text(node,id_field,entity); node.set('Time',str(at))
            if tag=='AirVehicleConfiguration': set_text(node,'Label','UAV '+entity)
            if tag=='MissionCommand': set_text(node,'CommandID',50000+index)
            translate(node,dlat,dlon); events.append(node)
        task=deepcopy(source[kind]); task_id=str(3000+index)
        set_text(task,'TaskID',task_id); set_text(task,'Label','G4_'+kind+'_'+entity)
        eligible=task.find('EligibleEntities'); eligible.clear(); ET.SubElement(eligible,'int64').text=entity
        # Fixed search requirements inherit the qualified original line task;
        # these are defined once, before any flight or performance measurement.
        for field in ('DesiredWavelengthBands','DwellTime','GroundSampleDistance'):
            for old in task.findall(field): task.remove(old)
            task.append(deepcopy(source['line'].find(field)))
        if kind=='point':
            center=task.find('SearchLocation/Location3D')
            translate(task,ANCHOR[0]-float(center.findtext('Latitude')),ANCHOR[1]-float(center.findtext('Longitude')))
        elif kind=='area':
            rectangle=task.find('SearchArea/Rectangle'); center=rectangle.find('CenterPoint/Location3D')
            translate(task,ANCHOR[0]-float(center.findtext('Latitude')),ANCHOR[1]-float(center.findtext('Longitude')))
            set_text(rectangle,'Width',1000); set_text(rectangle,'Height',500); set_text(rectangle,'Rotation',0)
        translate(task,dlat,dlon)
        task_file='task-'+task_id+'.xml'; write(task,directory/task_file)
        request=ET.Element('AutomationRequest',Series='CMASI')
        entities=ET.SubElement(request,'EntityList'); ET.SubElement(entities,'int64').text=entity
        tasks=ET.SubElement(request,'TaskList'); ET.SubElement(tasks,'int64').text=task_id
        set_text(request,'TaskRelationships',''); set_text(request,'OperatingRegion',0); set_text(request,'RedoAllTasks','false')
        request_file='request-'+task_id+'.xml'; write(request,directory/request_file)
        manifest['assignments'].append({'entityId':entity,'taskId':task_id,'kind':kind,'sourceEntityId':base,
            'latitudeOffsetDegrees':dlat,'longitudeOffsetDegrees':dlon,'taskFile':task_file,'requestFile':request_file})
    view=scenario.find('ScenarioData/SimulationView')
    view.set('Longitude',str(ANCHOR[1]+GRID[1]*(min(len(ids),5)-1)/2))
    view.set('Latitude',str(ANCHOR[0]+GRID[0]*((len(ids)-1)//5)/2))
    view.set('LongExtent',str(.11+GRID[1]*(min(len(ids),5)-1)))
    write(scenario,directory/'scenario.xml')
    manifest['files']=[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(directory.glob('*.xml'))]
    (directory/'scene.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest
