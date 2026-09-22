"""Read-only coverage reduction of committed G4 events, using AMASE's analysis rules.

This is display analysis, not a sensor/terrain-occlusion or task completion model.
Current qualified scenes use zero dwell and point/line/rectangle tasks.
"""
import hashlib
import json
import math
import sqlite3
import struct

RADIUS = 6378137.0
MAX_CELLS = 50000


def need(value, reason):
    if not value:
        raise ValueError(reason)


def number(value):
    need(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), 'Nonfinite coordinate')
    return float(value)


def point(value, qualified=True):
    lat, lon = number(value['Latitude']), number(value['Longitude'])
    need(-90 <= lat <= 90 and -180 <= lon <= 180, 'Invalid geographic coordinate')
    if qualified:
        need(45 <= lat < 46 and -122 <= lon < -120, 'Coverage outside qualified terrain')
    return lat, lon


def distance(a, b):
    lat, lon, other_lat, other_lon = map(math.radians, (*a, *b))
    q = math.sin((other_lat-lat)/2)**2 + math.cos(lat)*math.cos(other_lat)*math.sin((other_lon-lon)/2)**2
    return 2*RADIUS*math.asin(min(1, math.sqrt(q)))


def inside(lat, lon, polygon):
    value = False
    for a, b in zip(polygon, polygon[1:]+polygon[:1]):
        if (a[0] > lat) != (b[0] > lat) and lon < a[1]+(lat-a[0])*(b[1]-a[1])/(b[0]-a[0]):
            value = not value
    return value


def rectangle(shape):
    need(shape['_type'].endswith('.Rectangle'), 'Only qualified rectangle area tasks supported')
    lat, lon = map(math.radians, point(shape['CenterPoint']))
    w, h, angle = number(shape['Width']), number(shape['Height']), math.radians(number(shape['Rotation']))
    need(0 < w <= 100000 and 0 < h <= 100000, 'Invalid rectangle extent')
    result = []
    for x, y in ((-w/2,h/2),(w/2,h/2),(w/2,-h/2),(-w/2,-h/2)):
        bearing, arc = math.atan2(x,y)+angle, math.hypot(x,y)/RADIUS
        p = math.asin(math.sin(lat)*math.cos(arc)+math.cos(lat)*math.sin(arc)*math.cos(bearing))
        l = lon+math.atan2(math.sin(bearing)*math.sin(arc), math.cos(lat)*math.cos(arc)-math.sin(lat)*math.sin(arc)*math.cos(bearing))
        result.append((math.degrees(p),math.degrees(l)))
    return result


class Terrain:
    """Native qualified nonnegative DTED nearest node; no bilinear substitution."""
    def __init__(self, directory):
        self.tiles = {}
        for west in (-122,-121):
            data = (directory/'dted'/('w'+str(-west))/'n45.dt1').read_bytes()
            need(data[:3] == b'UHL' and len(data) == 3428+1201*2414, 'DTED layout differs')
            self.tiles[west] = data

    def nearest(self, lat, lon):
        point({'Latitude':lat,'Longitude':lon})
        west = math.floor(lon)
        col, row = math.floor((lon-west)*1200+.5), math.floor((lat-45)*1200+.5)
        value = struct.unpack_from('>H',self.tiles[west],3428+col*2414+8+row*2)[0]
        need(value < 32768, 'Unqualified negative or missing DTED')
        return value


class Task:
    def __init__(self, definition, remaining):
        self.definition = definition
        self.id = definition['TaskID']
        self.kind = definition['_type'].split('.')[-1]
        need(int(definition['DwellTime']) == 0, 'Nonzero dwell is not qualified for this coverage display')
        self.gsd = number(definition['GroundSampleDistance'])
        need(self.gsd >= 0, 'Invalid GSD')
        self.cells, self.seen, self.previous, self.intervals = [], set(), {}, []
        self.contributors = set()
        self.shape = None

        def add(cell):
            need(len(self.cells) < remaining, 'Coverage cell budget exceeded')
            point({'Latitude':cell[0],'Longitude':cell[1]})
            self.cells.append(cell)

        if self.kind == 'PointSearchTask':
            add(list(point(definition['SearchLocation'])))
        elif self.kind == 'LineSearchTask':
            points = [point(p) for p in definition['PointList']]
            need(2 <= len(points) <= 4096, 'Invalid line vertex count')
            for a, b in zip(points, points[1:]):
                count = int(distance(a,b)/20)+1
                need(count <= remaining-len(self.cells), 'Coverage line cell budget exceeded')
                for i in range(count):
                    add([a[0]+(b[0]-a[0])*i/count,a[1]+(b[1]-a[1])*i/count,
                         a[0]+(b[0]-a[0])*(i+1)/count,a[1]+(b[1]-a[1])*(i+1)/count])
        elif self.kind == 'AreaSearchTask':
            polygon = rectangle(definition['SearchArea'])
            north, south = max(p[0] for p in polygon), min(p[0] for p in polygon)
            west, east = min(p[1] for p in polygon), max(p[1] for p in polygon)
            dy = math.degrees(20/RADIUS)
            dx = dy/math.cos(math.radians((north+south)/2))
            cols, rows = math.ceil((east-west)/dx), math.ceil((north-south)/dy)
            need(cols*rows <= MAX_CELLS, 'Coverage rectangle allocation exceeds budget')
            self.shape = dict(west=west,north=north,dx=dx,dy=dy,columns=cols,rows=rows)
            for col in range(cols):
                for row in range(rows):
                    lat, lon = north-dy*(row+.5), west+dx*(col+.5)
                    if inside(lat,lon,polygon):
                        add([lat,lon,col,row])
        else:
            raise ValueError('Unsupported search task')
        need(self.cells, 'Empty coverage grid')
        # Spatial buckets only prune tests; they never alter native sample locations.
        self.buckets = {}
        for index, cell in enumerate(self.cells):
            self.buckets.setdefault((math.floor(cell[0]*100), math.floor(cell[1]*100)), []).append(index)

    def observe(self, state, camera, config, agl):
        sensor = (state['ID'],camera['PayloadID'])
        stamp = int(state['Time'])
        old = self.previous.get(sensor)
        if old and stamp <= old[0]:
            return
        # Native planar corner rays can extend beyond the qualified terrain.
        # They only classify qualified task samples; no outside heights are read.
        polygon = [point(p,False) for p in camera['Footprint']]
        need(len(polygon) <= 8, 'Camera footprint exceeds CMASI limit')
        qualified = False
        bands = self.definition['DesiredWavelengthBands']
        if len(polygon) >= 3 and (0 in bands or config['SupportedWavelengthBand'] in bands):
            resolution = int(config['VideoStreamHorizontalResolution'])
            fov = number(camera['HorizontalFieldOfView'])
            need(resolution > 0 and 0 < fov < 180, 'Camera resolution/FOV invalid')
            scale = math.sin(math.radians(fov)/resolution)
            source = point(state['Location'])
            north, south = max(p[0] for p in polygon), min(p[0] for p in polygon)
            west, east = min(p[1] for p in polygon), max(p[1] for p in polygon)
            keys = (key for key in self.buckets if math.floor(south*100) <= key[0] <= math.floor(north*100)
                    and math.floor(west*100) <= key[1] <= math.floor(east*100))
            for key in keys:
                for index in self.buckets.get(key, []):
                    if self.kind != 'PointSearchTask' and index in self.seen:
                        continue
                    lat, lon = self.cells[index][:2]
                    if inside(lat,lon,polygon) and math.hypot(distance(source,(lat,lon)),agl)*scale <= self.gsd:
                        self.seen.add(index)
                        self.contributors.add(state['ID'])
                        qualified = True
        self.previous[sensor] = (stamp,qualified)
        if self.kind == 'PointSearchTask' and qualified and old and old[1] and stamp-old[0] <= 1000:
            intervals = sorted(self.intervals+[(old[0],stamp)])
            merged = []
            for start,end in intervals:
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0],max(merged[-1][1],end))
                else:
                    merged.append((start,end))
            need(len(merged) <= 50000, 'Observation interval budget exceeded')
            self.intervals = merged

    def snapshot(self):
        return dict(taskId=self.id,kind=self.kind,cells=self.cells,seen=sorted(self.seen),grid=self.shape,
                    totalCells=len(self.cells),seenCells=len(self.seen),contributors=sorted(self.contributors),
                    observationMilliseconds=str(sum(b-a for a,b in self.intervals)))


class Coverage:
    def __init__(self, run_id, terrain):
        self.run_id,self.terrain = run_id,terrain
        self.tasks,self.configs,self.deleted_tasks,self.deleted_entities = {},{},{},set()
        self.cursor = (0,0)
        self.time,self.last_time,self.states,self.latest = 0,0,0,0

    def apply(self, event):
        need(event['run_id'] == self.run_id, 'Coverage run identity mismatch')
        key = tuple(int(event['event_id'][name]) for name in ('shard','row_id'))
        need(key == (self.cursor[0],self.cursor[1]+1) or key == (self.cursor[0]+1,1), 'Coverage event sequence gap')
        m = event['message'];f = m['fields'];kind = m['type'].split('.')[-1]
        if kind in ('AirVehicleConfiguration','AirVehicleState','SessionStatus'):
            need(m['sourceEntity'] == m['sourceService'] == '0', 'Coverage state authority mismatch')
        if kind == 'SessionStatus':
            self.time = int(f['ScenarioTime'])
        elif kind == 'AirVehicleConfiguration' and f['ID'] not in self.deleted_entities:
            need(len(self.configs) < 128 or f['ID'] in self.configs, 'Coverage entity budget')
            self.configs[f['ID']] = f
        elif kind in ('PointSearchTask','LineSearchTask','AreaSearchTask') and f['TaskID'] not in self.deleted_tasks:
            remaining = MAX_CELLS-sum(len(t.cells) for key,t in self.tasks.items() if key != f['TaskID'])
            need(len(self.tasks) < 128 or f['TaskID'] in self.tasks, 'Coverage task budget')
            self.tasks[f['TaskID']] = Task(f,remaining)
        elif kind == 'RemoveTasks':
            for identifier in f['TaskList']:
                self.tasks.pop(identifier,None);self.deleted_tasks[identifier] = True
        elif kind == 'RemoveEntities':
            for identifier in f['EntityList']:
                self.configs.pop(identifier,None);self.deleted_entities.add(identifier)
        elif kind == 'AirVehicleState' and f['ID'] not in self.deleted_entities:
            self.latest = max(self.latest,int(f['Time']))
            if self.time-self.last_time >= 500 or self.time == self.last_time:
                self.last_time = self.time
                cfg = self.configs.get(f['ID'])
                need(cfg is not None, 'Camera configuration missing')
                location = f['Location'];lat,lon = point(location)
                need(location['AltitudeType'] == 1, 'Unqualified aircraft altitude reference')
                agl = number(location['Altitude'])-self.terrain.nearest(lat,lon)
                need(agl >= 0, 'Aircraft below qualified terrain')
                payloads = cfg['PayloadConfigurationList']
                for camera in (p for p in payloads if p['_type'].endswith('.CameraConfiguration')):
                    linked = any(p['_type'].endswith('.GimbalConfiguration') and camera['PayloadID'] in p['ContainedPayloadList'] for p in payloads)
                    if not linked:
                        continue
                    states = [p for p in f['PayloadStateList'] if p['_type'].endswith('.CameraState') and p['PayloadID'] == camera['PayloadID']]
                    need(len(states) == 1, 'Camera state missing or duplicated')
                    for task in self.tasks.values():
                        task.observe(f,states[0],camera,agl)
                self.states += 1
        self.cursor = key

    def snapshot(self):
        return dict(schemaVersion=1,runId=self.run_id,cursor=[str(v) for v in self.cursor],
                    simulationTimeMs=str(self.latest),sampledStates=self.states,gridResolutionMeters=20,
                    tasks=[t.snapshot() for t in self.tasks.values()])


def read_batch(path, manifest, coverage, limit=512):
    connection = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.5)
    try:
        connection.execute('PRAGMA query_only=ON')
        metadata = connection.execute('SELECT binding FROM metadata WHERE id=1').fetchone()
        if metadata is None:
            raise sqlite3.OperationalError('Coverage ledger not initialized')
        binding = json.loads(metadata[0])
        need(binding['run_id'] == coverage.run_id and binding['processes'] == manifest['processes']
             and binding['journal_anchors'] == manifest['journal_anchors'], 'Coverage ledger binding differs')
        maximum = connection.execute('SELECT shard,row_id FROM events ORDER BY shard DESC,row_id DESC LIMIT 1').fetchone()
        if maximum is None and coverage.cursor == (0,0):
            return False
        need(maximum is not None and tuple(maximum) >= coverage.cursor, 'Coverage ledger truncated')
        records = connection.execute('SELECT shard,row_id,sha256,event FROM events WHERE (shard,row_id) > (?,?) ORDER BY shard,row_id LIMIT ?',(*coverage.cursor,limit)).fetchall()
    finally:
        connection.close()
    for shard,row,checksum,data in records:
        need(hashlib.sha256(data.encode()).hexdigest() == checksum, 'Coverage event checksum mismatch')
        event = json.loads(data)
        need(event['event_id'] == dict(shard=str(shard),row_id=str(row)), 'Coverage event key differs')
        coverage.apply(event)
    return coverage.cursor == tuple(maximum)
