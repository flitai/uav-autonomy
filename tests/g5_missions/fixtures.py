"""Explicit independent CMASI/G4 examples. These are not real backend evidence."""
import copy
BIG='9223372036854775807'
def location(lon=-120.7,lat=45.3,alt=1100,ref=1):
    return dict(_type='afrl.cmasi.Location3D',Longitude=lon,Latitude=lat,Altitude=alt,AltitudeType=ref)
def rectangle(rotation=0):return dict(_type='afrl.cmasi.Rectangle',CenterPoint=location(alt=99999),Width=1000,Height=500,Rotation=rotation)
def state():
    points=[]
    for number,next_number,lon in [('9',BIG,-120.71),(BIG,'3',-120.70),('3','3',-120.69)]:
        points.append(dict(location(lon),Number=number,NextWaypoint=next_number,AssociatedTasks=['11'],VehicleActionList=[],Speed=30,SpeedType=0))
    mission=dict(_type='afrl.cmasi.MissionCommand',VehicleID=BIG,CommandID='800',FirstWaypoint='9',WaypointList=[points[2],points[0],points[1]],VehicleActionList=[],Status=0)
    source=dict(fixture='independent-g5-t07',type='isolated protocol example')
    route=dict(entity_id=BIG,command_id='800',planned_mission=mission,source=source)
    task=lambda i,kind,**geometry:dict(task_id=i,kind=kind,definition=dict(TaskID=i,Label='独立示例 '+i,**geometry),eligible_entity_ids=[BIG],initialized=True,assignments=[dict(AssignedVehicle=BIG,TaskID=i,TimeTaskCompleted='123')],active=False,backend_completed=False,completed_entity_ids=[],source=source)
    tasks={'11':task('11','point',SearchLocation=location()),'12':task('12','line',PointList=[location(-120.705),location(-120.7,45.305),location(-120.695)]),'13':task('13','area',SearchArea=rectangle())}
    zone=lambda i,kind,boundary,lo=100,hi=2000:dict(kind=kind,definition=dict(ZoneID=i,Label='独立示例 '+kind,MinAltitude=lo,MinAltitudeType=0,MaxAltitude=hi,MaxAltitudeType=1,AffectedAircraft=[BIG],StartTime='0',EndTime=BIG,Padding=10,Boundary=boundary),source=source)
    zones={'21':zone('21','KeepInZone',rectangle(33)),'22':zone('22','KeepOutZone',dict(_type='afrl.cmasi.Circle',CenterPoint=location(-120.72),Radius=250)),
        '23':zone('23','KeepOutZone',dict(_type='afrl.cmasi.Polygon',BoundaryPoints=[location(-120.69,45.31),location(-120.685,45.31),location(-120.685,45.315),location(-120.69,45.315)])),
        'region:24':dict(kind='OperatingRegion',definition=dict(ID='24',KeepInAreas=['21'],KeepOutAreas=['22','23']),source=source)}
    return dict(entities={},routes={BIG:route},commands={},tasks=tasks,zones=zones,simulation=dict(simulation_time_ms='0',start_time_ms='0',state=2,real_time_multiple=1))
def snapshot():return dict(schema_version=1,kind='snapshot',run_id='independent-g5-t07',stream_id='fixture-stream',sequence='9007199254740993',source_time_ms='0',state=state())
