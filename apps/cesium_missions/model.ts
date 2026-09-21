import { array, record, location, altitude, surface, boundary, densify, numeric, type Heights, type Vertex } from './geometry.js';
import { decimal, need, type ObjectValue, type State } from '../state/protocol.js';

export type Category='plans'|'commands'|'execution'|'tasks'|'zones';
export interface Drawing { kind:'line'|'point'|'area'|'wall'; vertices:Vertex[]; lower?:Vertex[]; waypoint?:string; ground?:boolean }
export interface Feature { key:string; category:Category; title:string; status:string; entityIds:string[]; taskIds:string[]; related:string[]; details:[string,string][]; drawings:Drawing[]; source:unknown; error?:string; waypoints?:Waypoint[]; evidence?:unknown }
export interface Waypoint { id:string; next:string; vertex:Vertex; taskIds:string[]; raw:ObjectValue }
const id=(v:unknown)=>{decimal(v);return v;};
const ids=(v:unknown)=>array(v,'标识列表').map(id);
const unique=(v:string[])=>[...new Set(v)];
const typeName=(v:unknown)=>String(v).split('.').pop()!;
const refName=(v:unknown)=>v===0?'AGL':v===1?'MSL／EGM96':'未确认';
const time=(v:unknown)=>typeof v==='string'?v+' ms':'—';
export function waypoints(raw:unknown,h:Heights):Waypoint[] {
  const message=record(raw,'航线命令'),list=array(message.WaypointList,'航点列表');need(list.length>0&&list.length<=8192,'航点数超出显示上限或为空');
  const result=list.map(v=>{const w=record(v,'航点');return {id:id(w.Number),next:id(w.NextWaypoint),vertex:location(w,h),taskIds:ids(w.AssociatedTasks),raw:w};});
  need(new Set(result.map(w=>w.id)).size===result.length,'航点编号重复');id(message.FirstWaypoint);
  need(result.some(w=>w.id===message.FirstWaypoint),'起始航点缺失');return result;
}
export function links(points:Waypoint[]):Drawing[] {
  const byId=new Map(points.map(w=>[w.id,w]));return points.flatMap(w=>{
    if(w.next===w.id)return [];
    const next=byId.get(w.next);return next?[{kind:'line' as const,vertices:[w.vertex,next.vertex]}]:[];
  });
}
interface Observation { command:string; revision:string; waypoint:string; time:string; from?:string; source?:unknown }
export class MissionModel {
  features=new Map<string,Feature>(); private observations=new Map<string,Observation>();
  private cache=new Map<string,{signature:string;value:unknown}>();
  constructor(readonly heights:Heights,readonly maximumVertices=50000){}
  clear(){this.features.clear();this.observations.clear();this.cache.clear();}
  private memo<T>(key:string,input:unknown,build:()=>T):T {
    const signature=JSON.stringify(input),old=this.cache.get(key);if(old?.signature===signature)return old.value as T;
    const value=build();this.cache.set(key,{signature,value});return value;
  }
  update(state:State):void {
    const next=new Map<string,Feature>(),used=new Set<string>();let vertices=0;
    const make=(key:string,category:Category,title:string,raw:ObjectValue,body:(f:Feature)=>void)=>{
      used.add(key);const f:Feature={key,category,title,status:'未确认',entityIds:[],taskIds:[],related:[],details:[],drawings:[],source:raw.source};
      try {body(f);const count=(f.waypoints?.length??0)+f.drawings.reduce((n,d)=>n+d.vertices.length+(d.lower?.length??0),0);need(vertices+count<=this.maximumVertices,'业务几何超过显示缓存上限');vertices+=count;}
      catch(error){f.drawings=[];delete f.waypoints;this.cache.delete(key);if(category==='execution')this.observations.delete(key.slice('execution:'.length));f.error=String(error);f.status='显示未确认';}
      next.set(key,f);
    };
    for(const [entity,raw] of Object.entries(state.routes))make('plan:'+entity,'plans','完整规划 · 实体 '+entity,raw,f=>{
      need(raw.entity_id===entity,'规划实体身份不符');f.entityIds=[entity];
      const m=record(raw.planned_mission,'完整规划');need(m.VehicleID===entity&&m.CommandID===raw.command_id,'规划命令身份不符');
      const wp=this.memo(f.key,m,()=>waypoints(m,this.heights));f.waypoints=wp;f.taskIds=unique(wp.flatMap(w=>w.taskIds));
      f.drawings=links(wp);f.status='规划已收到';
      f.details=[['规划命令',id(raw.command_id)],['航点数',String(wp.length)],['起始航点',id(m.FirstWaypoint)],['末端行为',wp.some(w=>w.id===w.next)?'含终端自环航点':'按 NextWaypoint 连接']];
      const missing=wp.filter(w=>!wp.some(v=>v.id===w.next)).map(w=>w.next);if(missing.length)f.details.push(['未包含的目标航点',unique(missing).join('、')]);
    });
    for(const [key,raw] of Object.entries(state.commands))make('command:'+key,'commands','当前'+(raw.kind==='mission'?'航线':'动作')+'命令 · 实体 '+raw.entity_id,raw,f=>{
      const entity=id(raw.entity_id);f.entityIds=[entity];const m=record(raw.message,'命令');need(m.VehicleID===entity&&m.CommandID===raw.command_id,'命令身份不符');
      f.status=raw.received===true?'命令已收到':'接收未确认';f.details=[['命令编号',id(raw.command_id)],['命令状态字段',String(m.Status)],['动作',array(m.VehicleActionList,'动作列表').map(a=>typeName(record(a,'动作')._type)).join('、')||'无']];
      if(raw.kind==='mission') {
        const wp=this.memo(f.key,m,()=>waypoints(m,this.heights));f.waypoints=wp;f.drawings=links(wp);f.taskIds=unique(wp.flatMap(w=>w.taskIds));
        f.details.push(['分段航点数',String(wp.length)],['起始航点',id(m.FirstWaypoint)]);
      }
      const entityState=state.entities[entity];
      const confirmed=raw.kind==='mission'&&raw.received===true&&raw.execution_observed===true&&f.waypoints?.some(w=>w.id===raw.current_waypoint_id)&&entityState?.current_command_id===raw.command_id&&entityState?.current_waypoint_id===raw.current_waypoint_id&&entityState?.simulation_time_ms===raw.execution_time_ms;
      f.details.push(['执行证据',confirmed?'后端状态命令／航点匹配':'尚未确认当前执行'],['报告的当前航点',String(raw.current_waypoint_id??'—')],['观察时间',time(raw.execution_time_ms)]);
      if(confirmed)f.status='观察到执行';
    });
    for(const [entity,e] of Object.entries(state.entities)) {
      const command=state.commands[entity+':mission'],key='execution:'+entity;
      if(!command) {this.observations.delete(entity);continue;}
      make(key,'execution','执行目标 · 实体 '+entity,e,f=>{
        f.entityIds=[entity];f.related=['command:'+entity+':mission','plan:'+entity];
        const cf=next.get(f.related[0]);
        if(cf?.status!=='观察到执行'||!cf.waypoints){this.observations.delete(entity);f.details=[['执行航段','等待后端匹配当前命令和航点']];return;}
        const target=id(e.current_waypoint_id),commandId=id(e.current_command_id),timestamp=id(e.simulation_time_ms),revision=JSON.stringify(command.message);
        const prior=this.observations.get(entity),old=prior?.revision===revision?prior:undefined;
        const wp=cf.waypoints.find(w=>w.id===target);need(wp,'当前航点不在命令中');
        let from=old?.command===commandId?old.from:undefined;
        if(old?.command===commandId&&old.waypoint!==target) {
          const previous=cf.waypoints.find(w=>w.id===old.waypoint);
          from=BigInt(timestamp)>BigInt(old.time)&&previous?.next===target?previous.id:undefined;
        }
        if(old&&BigInt(timestamp)<BigInt(old.time))from=undefined;
        this.observations.set(entity,{command:commandId,revision,waypoint:target,time:timestamp,from,source:e.source});
        f.taskIds=ids(e.associated_task_ids);f.status='当前目标航点 '+target;
        f.drawings=[{kind:'point',vertices:[wp.vertex],waypoint:target}];
        const previous=from&&cf.waypoints.find(w=>w.id===from);
        if(previous)f.drawings.push({kind:'line',vertices:[previous.vertex,wp.vertex]});
        f.evidence={commandId,currentWaypoint:target,previousWaypoint:from??null,simulationTime:timestamp,source:e.source};
        f.details=[['命令',commandId],['当前目标',target],['执行航段',previous?from+' → '+target+'（观察到目标推进）':'未确认；快照不恢复航点推进历史'],['观察时间',time(timestamp)],['终端',wp.id===wp.next?'自环航点；完成不表示停飞':'否']];
      });
    }
    const taskNames:Record<string,string>={point:'点搜索',line:'线搜索',area:'区域搜索'};
    for(const [task,raw] of Object.entries(state.tasks))make('task:'+task,'tasks',(taskNames[String(raw.kind)]??'任务')+' · '+task,raw,f=>{
      f.taskIds=[task];f.status=raw.backend_completed===true?'后端报告完成':raw.active===true?'后端报告执行中':raw.initialized===true?'任务已初始化':'任务已定义';
      f.entityIds=unique([...(Array.isArray(raw.eligible_entity_ids)?ids(raw.eligible_entity_ids):[]),...(Array.isArray(raw.assignments)?raw.assignments.map(a=>id(record(a,'分配').AssignedVehicle)):[]),...(Array.isArray(raw.completed_entity_ids)?ids(raw.completed_entity_ids):[]),...(typeof raw.active_entity_id==='string'?[id(raw.active_entity_id)]:[])]);
      f.details=[['状态',f.status],['激活时间',time(raw.activated_time_ms)],['完成时间',time(raw.completed_time_ms)],['分配实体',Array.isArray(raw.assignments)?unique(raw.assignments.map(a=>id(record(a,'分配').AssignedVehicle))).join('、')||'未分配':'未分配']];
      const d=record(raw.definition,'任务定义');need(d.TaskID===task,'任务定义身份不符');f.details.unshift(['名称',String(d.Label??'')]);
      f.drawings=this.memo(f.key,d,()=>{
        if(raw.kind==='point')return [{kind:'point' as const,vertices:[location(d.SearchLocation,this.heights)]}];
        if(raw.kind==='line'){const v=array(d.PointList,'任务折线').map(v=>location(v,this.heights));need(v.length>=2,'任务折线不足两点');return [{kind:'line' as const,vertices:v}];}
        if(raw.kind==='area'){const v=densify(boundary(d.SearchArea,this.heights)).map(p=>surface(p,this.heights));return [{kind:'area' as const,vertices:v,ground:true},{kind:'line' as const,vertices:[...v,v[0]],ground:true}];}
        throw new Error('任务几何类型尚未支持');
      });
      f.details.push(['高度语义',raw.kind==='area'?'二维范围贴同源地形，忽略中心高度':'按 Location3D 高度基准转换一次']);
      if(raw.kind==='point'){
        const p=record(d.SearchLocation,'点任务位置'),v=f.drawings[0].vertices[0];
        f.details.push(['经纬度',v.longitude.toFixed(7)+'° / '+v.latitude.toFixed(7)+'°'],['原高度',String(p.Altitude)+' m '+refName(p.AltitudeType)],['正高／椭球高',v.msl.toFixed(2)+' / '+v.ellipsoid.toFixed(2)+' m']);
      }else if(raw.kind==='line'){
        const list=array(d.PointList,'任务折线');f.details.push(['完整折线顶点数',String(list.length)],['顶点高度基准',unique(list.map(p=>refName(record(p,'顶点').AltitudeType))).join('、')]);
      }else if(raw.kind==='area'){
        const shape=record(d.SearchArea,'区域几何');f.details.push(['几何',typeName(shape._type)]);
        if(typeName(shape._type)==='Rectangle')f.details.push(['宽／高',String(shape.Width)+' / '+String(shape.Height)+' m'],['旋转',String(shape.Rotation)+'°（从北顺时针）']);
      }
    });
    for(const [zone,raw] of Object.entries(state.zones))make('zone:'+zone,'zones',(raw.kind==='OperatingRegion'?'运行区域':raw.kind==='KeepInZone'?'允许区':'禁入区')+' · '+zone,raw,f=>{
      const d=record(raw.definition,'区域定义');f.details=[['名称',String(d.Label??'')]];
      if(raw.kind==='OperatingRegion') {
        need(zone==='region:'+id(d.ID),'运行区域身份不符');f.related=[...ids(d.KeepInAreas),...ids(d.KeepOutAreas)].map(k=>'zone:'+k);f.status='区域引用集合';
        f.details.push(['允许区',ids(d.KeepInAreas).join('、')||'无'],['禁入区',ids(d.KeepOutAreas).join('、')||'无']);return;
      }
      need(raw.kind==='KeepInZone'||raw.kind==='KeepOutZone','区域类型未支持');need(d.ZoneID===zone,'区域身份不符');
      f.entityIds=ids(d.AffectedAircraft);f.status='边界已收到';
      const low=numeric(d.MinAltitude,'下限'),high=numeric(d.MaxAltitude,'上限'),lr=numeric(d.MinAltitudeType,'下限类型'),hr=numeric(d.MaxAltitudeType,'上限类型');
      f.details.push(['下限',low+' m '+refName(lr)],['上限',high+' m '+refName(hr)],['开始／结束原值',id(d.StartTime)+' / '+id(d.EndTime)+' ms'],['生效状态','时间基准由后端定义，未推断当前生效'],['影响实体',f.entityIds.join('、')||'全部实体'],['边界缓冲',numeric(d.Padding,'边界缓冲')+' m（显示原边界）']);
      f.drawings=this.memo(f.key,d,()=>{
        const points=densify(boundary(d.Boundary,this.heights)),lower=points.map(p=>altitude(p,low,lr,this.heights)),upper=points.map(p=>altitude(p,high,hr,this.heights));
        need(lower.every((p,i)=>p.msl<=upper[i].msl),'区域上下界交叉');
        return [{kind:'wall' as const,vertices:[...upper,upper[0]],lower:[...lower,lower[0]]},{kind:'line' as const,vertices:[...upper,upper[0]]},{kind:'line' as const,vertices:[...lower,lower[0]]},{kind:'area' as const,vertices:upper}];
      });
    });
    for(const f of next.values()) {
      if(f.category==='zones'&&f.related.length){const missing=f.related.filter(k=>!next.has(k));if(missing.length)f.details.push(['缺少边界',missing.join('、')]);f.entityIds=unique(f.related.flatMap(k=>next.get(k)?.entityIds??[]));}
      if(f.category!=='tasks')f.related.push(...f.taskIds.map(k=>'task:'+k));
      else f.related.push(...[...next.values()].filter(v=>v.category!=='tasks'&&v.taskIds.some(t=>f.taskIds.includes(t))).map(v=>v.key));
    }
    for(const k of this.cache.keys())if(!used.has(k))this.cache.delete(k);
    for(const k of this.observations.keys())if(!state.entities[k])this.observations.delete(k);
    this.features=next;
  }
}
