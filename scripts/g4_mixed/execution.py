"""Independent per-assignment planning, real navigation and completion evidence."""
from collections import Counter
import importlib.util
from pathlib import Path


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def assess(root,bus,monitor,events,navigation,assignments,requests):
    helper=module('mixed_execution_geometry',root/'scripts/g3_execution/correlator.py')
    receipt_view=module('mixed_execution_receipts',root/'scripts/g4_recovery/navigation.py')
    need,xml,values=helper.need,helper.xml,helper.values
    navigation,transitions=receipt_view.execution_view(navigation,bus)
    decoded=[(r,xml(r)) for r in bus]
    wire=[(r,xml(r)) for r in monitor]
    internal=[(r,xml(r)) for r in events if r.get('kind')=='message']
    def select(tag): return [(r,n) for r,n in decoded if n.tag==tag]
    ids={a['entityId'] for a in assignments}; task_ids={a['taskId'] for a in assignments}
    need(len(ids)==len(task_ids)==len(assignments),'one-task-per-entity')
    completions=select('TaskComplete')
    need(len(completions)==len(assignments) and {n.findtext('TaskID') for _,n in completions}==task_ids,'complete-task-set')
    native_states={(n.findtext('ID'),n.findtext('Time')):(r,n) for r,n in internal if n.tag=='AirVehicleState'}
    onwire=Counter(r['rawSHA256'] for r,n in wire if n.tag=='AirVehicleState')
    busstates=select('AirVehicleState')
    need(not(Counter(r['rawSHA256'] for r,n in busstates)-onwire),'state-wire-mismatch')
    for entity in ids:
        rows=[(r,n) for r,n in busstates if n.findtext('ID')==entity]
        need(len(rows)>=5 and all(r['sourceEntity']==r['sourceService']=='0' for r,_ in rows),'state-authority')
        times=[int(n.findtext('Time')) for _,n in rows]
        need(all(b>a for a,b in zip(times,times[1:])),'state-time-order')
        need(len({helper.position(n.find('Location/Location3D')) for _,n in rows})>1,'static-entity')
        for _,n in rows:
            pair=native_states.get((entity,n.findtext('Time')))
            need(pair is not None and helper.equivalent(n,pair[1]),'state-native-mismatch')
    result=[]
    for assignment in assignments:
        task,entity,kind=assignment['taskId'],assignment['entityId'],assignment['kind']
        initialized=[(r,n) for r,n in select('TaskInitialized') if n.findtext('TaskID')==task]
        unique=[(r,n) for r,n in select('UniqueAutomationRequest') if values(n,'OriginalRequest/AutomationRequest/TaskList/int64')==[task]]
        need(len(initialized)==len(unique)==1,'task-or-request-duplicate')
        ir,init=initialized[0]; qr,request=unique[0]; request_id=request.findtext('RequestID')
        need(values(request,'OriginalRequest/AutomationRequest/EntityList/int64')==[entity],'request-wrong-entity')
        need(helper.semantic(request.find('OriginalRequest/AutomationRequest'))==helper.semantic(requests[task]),'request-not-original')
        unique_responses=[(r,n) for r,n in select('UniqueAutomationResponse') if n.findtext('ResponseID')==request_id]
        assigned=[(r,n) for r,n in select('TaskAssignmentSummary') if n.findtext('CorrespondingAutomationRequestID')==request_id]
        need(len(unique_responses)==len(assigned)==1,'planning-correlation')
        ur,unique_response=unique_responses[0]; ar,summary=assigned[0]
        response=unique_response.find('OriginalResponse/AutomationResponse')
        plains=[(r,n) for r,n in select('AutomationResponse') if helper.semantic(n)==helper.semantic(response)]
        need(len(plains)==1,'plain-response-not-unique'); pr,plain=plains[0]
        need(all(r['sourceEntity']=='100' for r in (ir,qr,ur,ar,pr)),'planning-source')
        need(ir['monotonicSeconds']<qr['monotonicSeconds']<ar['monotonicSeconds']<ur['monotonicSeconds'],'planning-order')
        assigned_tasks=summary.findall('TaskList/TaskAssignment')
        need(assigned_tasks and all(n.findtext('TaskID')==task and n.findtext('AssignedVehicle')==entity for n in assigned_tasks),'wrong-assignment')
        plans=plain.findall('MissionCommandList/MissionCommand')
        need(len(plans)==1 and plans[0].findtext('VehicleID')==entity,'peer-plan-overwritten')
        plan=plans[0]; points=plan.findall('WaypointList/Waypoint'); wp={n.findtext('Number'):n for n in points}
        order={n.findtext('Number'):i for i,n in enumerate(points)}
        need(len(wp)==len(points),'duplicate-waypoint-number')
        targets=[n.findtext('Number') for n in points if task in values(n,'AssociatedTasks/int64')]
        need(targets,'task-route-empty')
        need(all(set(values(n,'AssociatedTasks/int64'))<={task} for n in points),'peer-task-in-plan')
        complete=[(r,n) for r,n in completions if n.findtext('TaskID')==task][0]
        cr,cn=complete; completed_ms=int(cn.findtext('TimeTaskCompleted'))
        need(cr['sourceEntity']=='100' and values(cn,'EntitiesInvolved/int64')==[entity],'completion-identity')
        commands=[(r,n) for r,n in select('MissionCommand') if n.findtext('VehicleID')==entity and r['monotonicSeconds']>=pr['monotonicSeconds']]
        command_map={}; segments=[]
        for r,command in commands:
            cid=command.findtext('CommandID'); numbers=values(command,'WaypointList/Waypoint/Number')
            need(r['sourceEntity']=='100' and cid not in command_map,'command-source-or-duplicate')
            need(numbers and all(number in wp for number in numbers),'command-outside-plan')
            need([order[number] for number in numbers]==list(range(order[numbers[0]],order[numbers[-1]]+1)),'noncontiguous-command')
            need(command.findtext('FirstWaypoint') in numbers,'command-first-waypoint')
            for n in command.findall('WaypointList/Waypoint'):
                for field in ('Number','NextWaypoint','Latitude','Longitude','Altitude','AltitudeType','Speed','SpeedType','AssociatedTasks'):
                    need(helper.semantic(n.find(field))==helper.semantic(wp[n.findtext('Number')].find(field)),'command-plan-field:'+field)
            received=[(e,n) for e,n in internal if n.tag=='MissionCommand' and n.findtext('VehicleID')==entity and n.findtext('CommandID')==cid]
            need(len(received)==1 and helper.equivalent(command,received[0][1]),'command-native-receipt')
            need(sum(n.tag=='MissionCommand' and e['rawSHA256']==r['rawSHA256'] for e,n in wire)==1,'command-wire-receipt')
            command_map[cid]=(command,received[0][0]); segments.append({'commandId':cid,'waypoints':numbers,'rawSHA256':r['rawSHA256']})
        need(command_map,'missing-real-commands')
        nav=[n for n in navigation if n['entityId']==entity and n['commandId'] in command_map]
        need(nav and all(int(b['sequence'])>int(a['sequence']) and float(b['simTimeSeconds'])>=float(a['simTimeSeconds']) for a,b in zip(nav,nav[1:])),'navigation-order')
        path=[]
        for n in nav:
            need(n['mode']=='Waypoint' and n['waypoint'] in wp,'navigation-plan-mismatch')
            if not path or path[-1]!=n['waypoint']:
                if path: need(wp[path[-1]].findtext('NextWaypoint')==n['waypoint'],'native-waypoint-skip-or-regression')
                path.append(n['waypoint'])
        executable_targets=list(targets); start_anchor=None
        # WPM explicitly commands the second point of every initial plan. A
        # zero-standoff point task marks its planning start anchor as on-task,
        # unlike the line/area transit. Keep that point in the plan evidence,
        # but do not invent an executed target for it.
        if targets[0]==points[0].findtext('Number') and path[0]!=targets[0]:
            first_command=next(iter(command_map.values()))[0]
            first=points[0]; second=points[1]
            need(kind=='point' and first_command.findtext('FirstWaypoint')==second.findtext('Number')==path[0]
                 and first.findtext('NextWaypoint')==second.findtext('Number') and not first.findall('VehicleActionList/*'),
                 'unsupported-task-start-skip')
            start_distance=helper.distance(nav[0]['position'],helper.position(first))
            need(start_distance<=150,'planning-start-anchor-too-far')
            start_anchor={'waypoint':targets[0],'commandedFirstWaypoint':path[0],'distanceAtReceiptMeters':start_distance,
                          'meaning':'WPM initial planning anchor, not an executed target'}
            executable_targets=targets[1:]
        need(executable_targets and [number for number in path if number in targets]==executable_targets,'task-waypoints-incomplete-or-revisited')
        executed=[(r,helper.state(n)) for r,n in busstates if n.findtext('ID')==entity and n.findtext('CurrentCommand') in command_map]
        need(executed,'no-real-execution')
        for r,state in executed:
            command,receipt=command_map[state['commandId']]
            need(state['waypoint'] in values(command,'WaypointList/Waypoint/Number'),'state-command-mismatch')
            need(state['tasks']==values(wp[state['waypoint']],'AssociatedTasks/int64'),'state-task-mismatch')
            native=native_states[(entity,state['timeMs'])][0]
            need(int(receipt['sequence'])<int(native['sequence']),'execution-before-receipt')
            peers=[n for n in nav if n['commandId']==state['commandId'] and n['waypoint']==state['waypoint'] and abs(float(n['simTimeSeconds'])-int(state['timeMs'])/1000)<1]
            need(peers,'state-without-navigation')
            peer=min(peers,key=lambda n:abs(float(n['simTimeSeconds'])-int(state['timeMs'])/1000))
            need(helper.distance(peer['position'],state['position'])<10 and abs(peer['position'][2]-state['position'][2])<1,'state-navigation-position')
        final=targets[-1]; successor=wp[final].findtext('NextWaypoint')
        need(successor in wp and not values(wp[successor],'AssociatedTasks/int64'),'terminal-successor')
        terminal=[n for n in nav if n['waypoint']==successor and n['waypointReached']==final]
        need(terminal,'terminal-arrival-missing'); terminal=terminal[0]
        terminal_ms=round(float(terminal['simTimeSeconds'])*1000)
        need(terminal_ms<=completed_ms+1,'completion-before-arrival')
        distance=helper.distance(terminal['position'],helper.position(wp[final]))
        need(distance<=150,'terminal-distance')
        on=[(r,s) for r,s in executed if task in s['tasks']]; need(on,'task-never-active')
        off=[(r,s) for r,s in executed if int(s['timeMs'])>int(on[-1][1]['timeMs']) and task not in s['tasks']]
        need(off and off[0][1]['waypoint']==successor,'terminal-state-missing')
        off_r,off_s=off[0]
        need(terminal_ms<=int(off_s['timeMs'])+1<=completed_ms+1 and completed_ms-int(off_s['timeMs'])<=1000
             and off_r['monotonicSeconds']<=cr['monotonicSeconds'],'completion-before-terminal-state')
        need(all(s['waypoint']==successor for _,s in off),'post-terminal-regression')
        active=[(r,n) for r,n in select('TaskActive') if n.findtext('TaskID')==task]
        need(len(active)==1 and active[0][1].findtext('EntityID')==entity and active[0][0]['sourceEntity']=='100','active-identity')
        need(on[0][0]['monotonicSeconds']<=active[0][0]['monotonicSeconds']<cr['monotonicSeconds'],'active-order')
        legs=[]
        for target in targets:
            index=order[target]
            if not index: continue
            samples=[n for n in nav if n['waypoint']==target and n.get('sampleKind')=='step' and float(n['simTimeSeconds'])*1000<=terminal_ms]
            if len(samples)<3: continue
            metrics=helper.segment_geometry([dict(n,timeMs=str(round(float(n['simTimeSeconds'])*1000))) for n in samples],
                                             helper.position(points[index-1]),helper.position(wp[target]))
            qualifies=metrics['forwardProgressMeters']>=10 and metrics['approachMeters']>=10 and metrics['maximumCrossTrackMeters']<=300 and metrics['altitudeErrorMeters']<=25
            legs.append({'target':target,'qualifies':qualifies,**metrics})
        need(sum(n['qualifies'] for n in legs)>=(2 if kind=='line' else 1),'real-task-leg-not-proven')
        need(any(n['target']==final and n['qualifies'] for n in legs),'terminal-task-leg-not-proven')
        result.append({'taskId':task,'entityId':entity,'kind':kind,'status':'passed','requestId':request_id,
            'taskWaypoints':targets,'executedTaskTargets':executable_targets,'planningStartAnchor':start_anchor,
            'segments':segments,'nativeTargetSequence':path,'taskLegs':legs,'terminal':terminal,
            'terminalDistanceMeters':distance,'completedTimeMs':str(completed_ms),'completionRawSHA256':cr['rawSHA256']})
    return {'status':'passed','tasks':result,'receiptOnlyTransitions':transitions,'taskExecutionValidated':True,'taskCompletionValidated':True}
