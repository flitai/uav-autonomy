"""Independent geometry, camera coverage and sampled point-time reconstruction."""
import base64
import importlib.util
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def helper(root):
    spec=importlib.util.spec_from_file_location('mixed_coverage_geometry',root/'scripts/g3_completion/coverage.py')
    value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def location(node): return float(node.findtext('Latitude')),float(node.findtext('Longitude'))


def area_grid(task,geometry):
    rectangle=task.find('SearchArea/Rectangle'); geometry.need(rectangle is not None,'rectangle-required')
    latitude,longitude=map(math.radians,location(rectangle.find('CenterPoint/Location3D')))
    width,height=float(rectangle.findtext('Width')),float(rectangle.findtext('Height'))
    geometry.need(width==1000 and height==500 and float(rectangle.findtext('Rotation'))==0,'fixed-rectangle-changed')
    angle=math.atan2(width,height); arc=math.hypot(width/2,height/2)/6378137
    polygon=[]
    for bearing in (-angle,angle,math.pi-angle,math.pi+angle):
        lat=math.asin(math.sin(latitude)*math.cos(arc)+math.cos(latitude)*math.sin(arc)*math.cos(bearing))
        lon=longitude+math.atan2(math.sin(bearing)*math.sin(arc),math.cos(latitude)*math.cos(arc)-math.sin(latitude)*math.sin(arc)*math.cos(bearing))
        polygon.append((math.degrees(lat),math.degrees(lon)))
    north,south=max(p[0] for p in polygon),min(p[0] for p in polygon)
    east,west=max(p[1] for p in polygon),min(p[1] for p in polygon)
    dy=math.degrees(20/6378137); dx=dy/math.cos(math.radians((north+south)/2))
    cells=[]
    for col in range(math.ceil((east-west)/dx)):
        for row in range(math.ceil((north-south)/dy)):
            lat,lon=north-dy*(row+.5),west+dx*(col+.5)
            if geometry.inside(lat,lon,polygon): cells.append({'row':col,'column':row,'latitude':lat,'longitude':lon})
    return cells


def inspect(root,directory,assignments):
    geometry=helper(root); need=geometry.need
    report=ET.parse(directory/'amase/analysis.xml').find('SearchTaskAnalysis')
    details=ET.parse(directory/'amase/coverage-cells.xml').getroot()
    need(float(details.get('GridResolutionMeters'))==20,'grid-resolution-changed')
    expected_ids={r['taskId'] for r in assignments}
    need({n.get('ID') for n in report}=={n.get('ID') for n in details}==expected_ids,'analysis-task-set')
    tasks={}
    for row in assignments:
        task=ET.parse(directory/'scene'/row['taskFile']).getroot(); kind=row['kind']; key=row['taskId']
        need(task.findtext('DwellTime')=='0','mixed-replay-expects-fixed-zero-dwell')
        if kind=='line': cells=geometry.grid(task)
        elif kind=='area': cells=area_grid(task,geometry)
        else:
            lat,lon=location(task.find('SearchLocation/Location3D'))
            cells=[{'row':0,'column':0,'latitude':lat,'longitude':lon}]
        native=details.find("Task[@ID='"+key+"']").findall('Cell')
        need(len(native)==len(cells) and cells,'analysis-cell-count')
        for observed,expected in zip(native,cells):
            need(int(observed.get('row'))==expected['row'] and int(observed.get('column'))==expected['column'],'cell-index')
            need(abs(float(observed.get('latitude'))-expected['latitude'])<1e-10 and
                 abs(float(observed.get('longitude'))-expected['longitude'])<1e-10,'cell-coordinate')
        node=report.find({'line':'SearchLine','area':'SearchArea','point':'SearchPoint'}[kind]+"[@ID='"+key+"']")
        need(node is not None,'report-task-kind')
        tasks[key]={'definition':task,'kind':kind,'cells':cells,'native':native,'report':node,'seen':set(),
                    'previous':{},'intervals':[],'states':0,'contributors':set(),'entity':row['entityId'],'started':False,
                    'seenByEntity':{},'intervalsByEntity':{}}
    configs={}; time=0; last_time=0
    for line in (directory/'amase/analysis-events.tsv').read_text().splitlines():
        _,encoded=line.split('\t',1); node=ET.fromstring(base64.b64decode(encoded))
        if node.tag=='AirVehicleConfiguration': configs[node.findtext('ID')]=node
        elif node.tag in ('PointSearchTask','LineSearchTask','AreaSearchTask'):
            key=node.findtext('TaskID'); need(key in tasks and not tasks[key]['started'],'unexpected-or-repeated-analysis-task')
            tasks[key]['started']=True
        elif node.tag=='SessionStatus': time=int(node.findtext('ScenarioTime'))/1000
        elif node.tag=='AirVehicleState':
            if time-last_time<.5 and time!=last_time: continue
            last_time=time; entity=node.findtext('ID'); milliseconds=int(node.findtext('Time'))
            config=configs.get(entity); need(config is not None,'state-without-configuration')
            position=location(node.find('Location/Location3D')); altitude=float(node.findtext('Location/Location3D/Altitude'))
            for task in tasks.values():
                if not task['started']: continue
                task['states']+=1
                seen_by_entity=task['seenByEntity'].setdefault(entity,set())
                desired=[n.text for n in task['definition'].findall('DesiredWavelengthBands/WavelengthBand')]
                for camera in config.findall('PayloadConfigurationList/CameraConfiguration'):
                    camera_id=camera.findtext('PayloadID'); sensor=(entity,camera_id)
                    if not any(camera_id in [p.text for p in g.findall('ContainedPayloadList/int64')]
                               for g in config.findall('PayloadConfigurationList/GimbalConfiguration')): continue
                    prior=task['previous'].get(sensor)
                    if task['kind']=='point' and prior and milliseconds<=prior[0]: continue
                    state=node.find("PayloadStateList/CameraState[PayloadID='"+camera_id+"']")
                    need(state is not None,'camera-state-missing')
                    footprint=state.findall('Footprint/Location3D'); polygon=[location(p) for p in footprint]
                    need(all(float(p.findtext('Altitude'))==0 for p in footprint),'nonzero-terrain-not-qualified')
                    band='AllAny' in desired or camera.findtext('SupportedWavelengthBand') in desired
                    pixel_angle=math.radians(float(state.findtext('HorizontalFieldOfView')))/int(camera.findtext('VideoStreamHorizontalResolution'))
                    qualified=False
                    for index,cell in enumerate(task['cells']):
                        if task['kind']!='point' and index in seen_by_entity: continue
                        lat,lon=cell['latitude'],cell['longitude']
                        visible=band and len(polygon)>=3 and geometry.inside(lat,lon,polygon)
                        visible=visible and math.hypot(geometry.distance(position,(lat,lon)),altitude)*math.sin(pixel_angle)<=float(task['definition'].findtext('GroundSampleDistance'))
                        if visible:
                            task['seen'].add(index); seen_by_entity.add(index)
                            task['contributors'].add(entity); qualified=True
                    if task['kind']=='point':
                        if prior and prior[1] and qualified and milliseconds-prior[0]<=1000:
                            task['intervals'].append((prior[0],milliseconds))
                            task['intervalsByEntity'].setdefault(entity,[]).append((prior[0],milliseconds))
                        task['previous'][sensor]=(milliseconds,qualified)
    results=[]
    for key,task in tasks.items():
        need(task['started'] and task['states']>0,'empty-analysis')
        expected={i for i,n in enumerate(task['native']) if n.get('seen')=='true'}
        need(task['seen']==expected,'independent-sensor-replay-differs')
        # Native SearchTaskAnalysis checks every actual camera against every
        # task. Incidental observation is distinct from planning eligibility;
        # preserve the native union and report assigned-only evidence separately.
        result={'taskId':key,'kind':task['kind'],'entityId':task['entity'],'status':'passed',
                'independentReplayStates':task['states'],'contributingEntities':sorted(task['contributors']),
                'nativeScope':'all actual sensors; independent of task execution assignment'}
        if task['kind']=='point':
            def duration(intervals):
                total=0; end=-1
                for first,last in sorted(intervals):
                    total+=max(0,last-max(first,end)); end=max(end,last)
                return total
            total=duration(task['intervals'])
            reported=float(task['report'].findtext('TimeSeenSec'))
            need(abs(total/1000-reported)<=.00500001,'point-seconds-report-differs')
            result.update(observationMilliseconds=str(total),observationSeconds=total/1000,reportedSeconds=reported,
                          assignedEntityObservationMilliseconds=str(duration(task['intervalsByEntity'].get(task['entity'],[]))),
                          observationMillisecondsByEntity={entity:str(duration(intervals)) for entity,intervals in sorted(task['intervalsByEntity'].items())},
                          intervalMeaning='union of consecutive qualified samples from the same sensor; gaps over 1000 ms excluded')
        else:
            count=len(task['cells']); seen=len(task['seen']); percent=100*seen/count
            need(int(task['report'].findtext('TotalCells'))==count and int(task['report'].findtext('SeenCells'))==seen,'coverage-count-report-differs')
            need(abs(float(task['report'].findtext('CoveragePercent'))-percent)<=.00500001,'coverage-percent-report-differs')
            by_entity={entity:len(cells) for entity,cells in sorted(task['seenByEntity'].items())}
            result.update(gridResolutionMeters=20,totalCells=count,seenCells=seen,coveragePercent=percent,
                          assignedEntitySeenCells=by_entity.get(task['entity'],0),seenCellsByEntity=by_entity)
        results.append(result)
    return {'status':'passed','tasks':results,'minimumCoveragePercent':None,'minimumObservationSeconds':None,'terrain':'zero-elevation-fallback'}
