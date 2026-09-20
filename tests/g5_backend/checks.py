"""Independent terrain, scene, actual execution and statistics qualification."""
from array import array
import base64
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import re
import struct
import sys
from urllib.parse import unquote, urlparse
from xml.dom import minidom
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('terrain_checks_common',ROOT/'scripts/g5_backend/common.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

class Terrain:
    """Read signed-magnitude DTED directly, without GDAL, Java or production samplers."""
    def __init__(self,directory):
        self.tiles={}
        for west in (-122,-121):
            data=(directory/'dted'/('w'+str(-west))/'n45.dt1').read_bytes()
            c.need(data[:3]==b'UHL' and len(data)==3428+1201*(12+2402),'Invalid DTED bytes')
            c.need(int(data[20:24])==int(data[24:28])==30,'DTED spacing is not 3 arcseconds')
            c.need(int(data[47:51])==int(data[51:55])==1201,'DTED dimensions differ')
            self.tiles[west]=data

    def node(self,west,col,row):
        offset=3428+col*2414+8+row*2
        value=struct.unpack_from('>H',self.tiles[west],offset)[0]
        c.need(value<32768,'Negative/invalid DTED is not qualified for the formal reader')
        return value

    def nearest(self,lat,lon):
        c.need(math.isfinite(lat) and math.isfinite(lon) and 45<=lat<46 and -122<=lon<-120,'Unqualified DTED query')
        west=math.floor(lon)
        return self.node(west,math.floor((lon-west)*1200+.5),math.floor((lat-45)*1200+.5))

    def intercept(self,values,level):
        # Independently reconstruct the native sampled-ray contract. It is a
        # spherical, sampled-height approximation, not exact mesh intersection.
        lat,lon,height,heading,slope,maximum=values
        c.need(level==1,'Unexpected sensor terrain level')
        tangent=math.tan(slope)
        if slope>=0 or maximum<=0:maximum=math.sqrt(2*6378137*height+height*height)
        maximum=min(maximum,abs(height/tangent) if tangent else math.inf)
        a,b,arc=math.radians(lat),math.radians(lon),maximum/6378137
        lat2=math.degrees(math.asin(math.sin(a)*math.cos(arc)+math.cos(a)*math.sin(arc)*math.cos(heading)))
        lon2=math.degrees(b+math.atan2(math.sin(arc)*math.sin(heading),math.cos(a)*math.cos(arc)-math.sin(a)*math.sin(arc)*math.cos(heading)))
        steps=int(math.hypot(lat2-lat,lon2-lon)/(3/3600))
        if not steps:return [lat,lon,self.nearest(lat,lon)]
        previous=height;previous_ground=0
        for i in range(steps):
            x,y=lat+(lat2-lat)*i/steps,lon+(lon2-lon)*i/steps
            ground=self.nearest(x,y);ray=height-height*i/steps
            if ray<=ground:
                fraction=(previous_ground-previous)/(ray-previous-ground+previous_ground)
                position=(i-1+fraction)/steps
                return [lat+(lat2-lat)*position,lon+(lon2-lon)*position,previous_ground+(ground-previous_ground)*fraction]
            previous,previous_ground=ray,ground
        return [lat2,lon2,self.nearest(lat2,lon2)]

def floats(path):
    values=array('f');values.frombytes(path.read_bytes())
    if sys.byteorder!='little':values.byteswap()
    return values

def canonical(values,lat,lon):
    x,y=(lon+122)*1200,(46-lat)*1200
    i,j=int(math.floor(x)),int(math.floor(y));dx,dy=x-i,y-j
    return sum(values[(j+b)*2401+i+a]*(dx if a else 1-dx)*(dy if b else 1-dy) for a,b in ((0,0),(1,0),(0,1),(1,1)))

def prepared(root,directory):
    terrain=Terrain(directory);values=floats(directory/'orthometric.f32')
    c.need(len(values)==2401*1201 and all(math.isfinite(v) and v>=0 for v in values),'Canonical grid invalid')
    maximum_error=0
    for west in (-122,-121):
        for col in range(1201):
            data=terrain.tiles[west];offset=3428+col*2414
            c.need(data[offset]==0xaa and sum(data[offset:offset+2410])==struct.unpack_from('>I',data,offset+2410)[0],'DTED column checksum differs')
            for row in range(1201):
                value=terrain.node(west,col,row);reference=values[(1200-row)*2401+(west+122)*1200+col]
                c.need(value==round(reference),'DTED not derived from common canonical grid')
                maximum_error=max(maximum_error,abs(value-reference))
    c.need(maximum_error<=.5,'DTED quantization exceeds half metre')
    c.need(all(terrain.node(-122,1200,i)==terrain.node(-121,0,i) for i in range(1201)),'DTED seam differs')
    adaptation=c.load(directory/'adaptation.json');window=adaptation['postWindow']
    subset=[values[y*2401+x] for y in range(window['top'],window['bottom']+1) for x in range(window['left'],window['right']+1)]
    maximum=max(max(subset),max(round(v) for v in subset));lift=adaptation['uniformFlightLiftMeters']
    c.need(abs(adaptation['maximumCanonicalMeters']-max(subset))<1e-7,'Envelope height maximum differs')
    c.need(lift==max(0,math.ceil(maximum+100-adaptation['minimumOriginalFlightMeters'])),'Flight height rule changed')
    checks=[];ground_points=0;flying=[]
    for name in ('original','small','mixed20'):
        scene=c.load(directory/name/'scene.json')
        c.need(scene['heightDatum']=='EPSG:5773' and scene['uniformFlightLiftMeters']==lift,'Scene datum/lift differs')
        if name=='mixed20':
            kinds=[a['kind'] for a in scene['assignments']]
            c.need(len(kinds)==20 and kinds.count('line')==8 and kinds.count('point')==6 and kinds.count('area')==6,'Mixed20 assignments changed')
        for path in sorted((directory/name).glob('*.xml')):
            old=ET.parse(directory/'unadapted'/name/path.name).getroot();new=ET.parse(path).getroot()
            old_positions=[(n.findtext('Latitude'),n.findtext('Longitude')) for n in old.iter() if n.find('Latitude') is not None and n.find('Longitude') is not None]
            new_positions=[(n.findtext('Latitude'),n.findtext('Longitude')) for n in new.iter() if n.find('Latitude') is not None and n.find('Longitude') is not None]
            c.need(old_positions==new_positions,'Horizontal geometry modified')
            if old.tag=='LineSearchTask':c.need(len(old.findall('PointList/Location3D'))==90,'Waterway was shortened')
            if path.name=='scenario.xml':
                heights=lambda n:[float(v.text) for v in n.iter() if v.tag in ('Altitude','NominalAltitude')]
                c.need(all(abs(b-a-lift)<1e-7 for a,b in zip(heights(old),heights(new))),'Nonuniform flight lift')
                flying+=heights(new)
            elif path.name.startswith('task-'):
                for n in new.iter():
                    if n.find('Latitude') is None or n.find('Longitude') is None:continue
                    lat,lon=float(n.findtext('Latitude')),float(n.findtext('Longitude'))
                    c.need(n.findtext('AltitudeType')=='MSL' and abs(float(n.findtext('Altitude'))-canonical(values,lat,lon))<1e-6,'Task height not canonical H96')
                    ground_points+=1
            def semantic(n):
                return (n.tag,(n.text or '').strip(),tuple(semantic(k) for k in n if k.tag not in ('Altitude','NominalAltitude','AltitudeType','ScenarioName')))
            c.need(semantic(old)==semantic(new),'Unrelated scene or coverage parameter modified')
        checks.append(name)
    c.need(min(flying)-maximum>=100,'Frozen flight clearance below 100 m')
    rejected=[]
    for lat,lon in [(46,-121),(45.5,-120),(44.999,-121),(45.5,-122.001),(float('nan'),-121)]:
        try:terrain.nearest(lat,lon)
        except RuntimeError:rejected.append([str(lat),str(lon)])
        else:raise RuntimeError('Bad boundary accepted')
    damaged=deepcopy(terrain);data=bytearray(damaged.tiles[-122]);struct.pack_into('>H',data,3428+8,0x8064);damaged.tiles[-122]=bytes(data)
    try:damaged.nearest(45,-122)
    except RuntimeError:rejected.append('negative-signed-magnitude')
    else:raise RuntimeError('Negative height not refused')
    return dict(status='passed',scenes=checks,groundTaskPoints=ground_points,quantizationMaxErrorMeters=maximum_error,
        uniformFlightLiftMeters=lift,minimumClearanceMeters=min(flying)-maximum,commonEdgePosts=1201,rejections=rejected)

def call_audit(root):
    files=['Core/avtas/terrain/DTEDTile.java','Core/avtas/terrain/DTEDCache.java','Core/avtas/terrain/TerrainService.java',
        'Amase/avtas/amase/entity/modules/KinematicFlight.java','Amase/avtas/amase/entity/modules/CameraControl.java',
        'Amase/avtas/amase/analysis/SearchTaskAnalysis.java']
    prefix=root/'OpenAMASE/OpenAMASE/src'
    tile=(prefix/files[0]).read_text(encoding='utf-8')
    c.need('readInt(20, 4) / 3600.0' in tile and 'readInt(24, 4) / 3600.0' in tile,'Known spacing defect changed; reassess qualification')
    # These fields have no read sites in DTEDTile/Cache or actual core consumers.
    for name in files[1:]:
        c.need(not re.search(r'\.(dlat|dlon)\b',(prefix/name).read_text(encoding='utf-8')),'Spacing metadata is consumed')
    return dict(status='passed',formalSourcesUnmodified=True,inputs=c.base.inventory(root,[prefix/f for f in files]),
        spacing='Queries use node counts; ray stepping uses static getPostSpacing(1)=3/3600',
        negativeDted='Known signed-magnitude decoding defect retained; nonnegative region only',
        sensor='Center ray samples terrain; corner projection uses a local flat plane and zero height fields',
        statistics='Nearest DTED at aircraft position supplies AGL for GSD; native footprint supplies horizontal polygon')

def accept(root,candidate,flight_id,output):
    c.need(flight_id and re.fullmatch(r'g5-t04-run-[a-z0-9-]+',flight_id),'Explicit completed flight identity required')
    flight=root/'out/runs'/flight_id;parent=c.load(flight/'result.json');context=c.load(flight/'context.json')
    c.need(parent['status']==c.load(flight/'entry-result.json')['status']=='passed','Flight entry failed')
    c.need(context['terrainCandidateSHA256']==c.sha(candidate/'candidate.json') and Path(context['terrainCandidate'])==candidate,'Flight candidate differs')
    c.need(parent['inputs']==c.sources(root),'Flight sources changed')
    c.need({case['mode'] for case in parent['cases']}=={'Gui','Headless'},'Both backend modes required')
    prep=prepared(root,candidate);audit=call_audit(root);terrain=Terrain(candidate)
    execution=c.module('terrain_independent_execution',root/'scripts/g4_mixed/execution.py')
    stats=c.module('terrain_independent_statistics',Path(__file__).with_name('statistics.py'))
    geometry=c.module('terrain_execution_geometry',root/'scripts/g3_execution/correlator.py')
    sys.path.insert(0,str(root/'out/generated/lmcp/py'))
    from lmcp.LMCPFactory import LMCPFactory,packMessage
    evidence=[]
    for case in parent['cases']:
        directory=flight/case['name'];receipt=c.load(directory/'case-result.json')
        c.need(receipt['status']=='passed' and receipt['normalExit'] and receipt['portsReleased'] and not receipt.get('cleanupErrors'),'Flight did not close normally')
        c.base.verify_files(directory,[dict(path=v['path'],sha256=v['sha256'].lower()) for v in receipt['evidence']])
        bus,wire,events=rows(directory/'observer.jsonl'),rows(directory/'amase.jsonl'),rows(directory/'amase/events.jsonl')
        initialized=[r for r in events if r['kind']=='initialized-paused'];c.need(len(initialized)==1,'Missing unique initialization')
        for key,digest in [('amaseSource',parent['artifacts']['amaseSHA256']),('lmcpSource',parent['artifacts']['lmcpSHA256'])]:
            path=Path(unquote(urlparse(initialized[0][key]).path.lstrip('/')))
            c.need(c.sha(path)==digest.lower(),'Loaded class differs')
        loaded=c.load(directory/'amase/terrain-loaded.json')
        for key in ('tileSource','cacheSource'):
            path=Path(unquote(urlparse(loaded[key]).path.lstrip('/')))
            c.need(c.sha(path)==parent['artifacts']['amaseSHA256'].lower(),'Terrain implementation was shadowed')
        c.need(sum(r['kind']=='start-request' for r in events)==1 and any(r['kind']=='shutdown' for r in events),'Native lifecycle differs')
        c.need(all(not (directory/(name+'-tail.bin')).read_bytes() for name in ('amase','observer')),'TCP tail missing')
        nav=[r for path in (directory/'amase').glob('execution-*.jsonl') for r in rows(path)]
        minimum=math.inf
        for n in nav:
            lat,lon,height=n['position'];ground=terrain.nearest(lat,lon)
            minimum=min(minimum,height-ground)
        c.need(minimum>=100-.001,'Actual flight clearance below 100 m')
        for row in bus:
            if row['type'] not in ('afrl.cmasi.MissionCommand','afrl.cmasi.AutomationResponse'):continue
            node=ET.fromstring(base64.b64decode(row['xmlBase64']))
            for waypoint in node.iter('Waypoint'):
                lat,lon,height=[float(waypoint.findtext(k)) for k in ('Latitude','Longitude','Altitude')]
                c.need(waypoint.findtext('AltitudeType')=='MSL' and height-terrain.nearest(lat,lon)>=100-.001,'Planned route datum/clearance invalid')
        requests={};injections=[]
        for row in receipt['scene']['assignments']:
            for purpose,file in [('task',row['taskFile']),('automation-request',row['requestFile'])]:
                with minidom.parse(str(directory/'scene'/file)) as document:
                    factory=LMCPFactory();node=document.documentElement
                    obj=factory.createObjectByName(node.getAttribute('Series'),node.tagName);obj.unpackFromXMLNode(node,factory)
                import hashlib
                digest=hashlib.sha256(bytes(packMessage(obj,True))).hexdigest();injections.append((purpose,digest))
                if purpose=='automation-request':requests[row['taskId']]=ET.fromstring(obj.toXMLStr(''))
                else:c.need(sum(r['type']==obj.FULL_LMCP_TYPE_NAME and r['rawSHA256'].lower()==digest for r in wire)==1,'Task not received exactly once')
        c.need(injections==[(r['purpose'],r['rawSHA256'].lower()) for r in receipt['injections'] if r['purpose'] in ('task','automation-request')],'Injection content/order differs')
        proof=execution.assess(root,bus,wire,events,nav,receipt['scene']['assignments'],requests)
        statistics=stats.inspect(root,directory,receipt['scene']['assignments'],terrain)
        queries=rows(directory/'amase/terrain-queries.jsonl')
        c.need(queries and all(q['height']==terrain.nearest(q['latitude'],q['longitude']) for q in queries),'Native terrain samples differ')
        rays=rows(directory/'amase/terrain-rays.jsonl');errors=[]
        for ray in rays:
            reference=terrain.intercept(ray['input'],ray['level'])
            errors.append(max(abs(a-b)*(111320 if i<2 else 1) for i,(a,b) in enumerate(zip(reference,ray['result']))))
        c.need(errors and max(errors)<.01,'Independent sensor ray reconstruction differs')
        c.need(any(ray['result'][2]>0 for ray in rays),'No actual terrain-dependent camera ray')
        # A changed captured native count must be rejected by the independent replay.
        case_output=output/case['name'];case_output.mkdir()
        c.save(case_output/'execution.json',proof);c.save(case_output/'statistics.json',statistics)
        c.save(case_output/'terrain.json',dict(querySamples=len(queries),raySamples=len(rays),maximumRayNumericalErrorMeters=max(errors),
            minimumObservedClearanceMeters=minimum,exactNearestMatches=True,rayApproximationNotSurveyAccuracy=True))
        evidence.append(dict(mode=case['mode'],status='passed',tasks=[dict(taskId=t['taskId'],entityId=t['entityId'],completedTimeMs=t['completedTimeMs']) for t in proof['tasks']],
            independentExecution=True,independentStatistics=True,querySamples=len(queries),raySamples=len(rays),minimumObservedClearanceMeters=minimum))
    c.save(output/'scene-checks.json',prep);c.save(output/'call-audit.json',audit)
    return evidence
