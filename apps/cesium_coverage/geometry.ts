import { need, type ObjectValue } from '../state/protocol.js';
import { array, numeric, record, surface, type Heights, type XY } from '../missions/geometry.js';

export function footprint(raw:unknown,h:Heights):{points:XY[];clipped:boolean;raw:XY[]} {
  const vertices=array(raw,'相机覆盖边界');need(vertices.length<=8,'相机覆盖边界超过 CMASI 上限');
  const original:XY[]=vertices.map(value=>{
    const p=record(value,'覆盖角点'),lon=numeric(p.Longitude,'经度'),lat=numeric(p.Latitude,'纬度');
    need(lon>=-180&&lon<=180&&lat>=-90&&lat<=90,'覆盖角点经纬度无效');return [lon,lat];
  });
  if(original.length<3)return {points:[],clipped:false,raw:original};
  need(Math.max(...original.map(p=>p[0]))-Math.min(...original.map(p=>p[0]))<180,'不支持跨日期变更线覆盖');
  let points=original;
  // Clip only the DISPLAY to the qualified terrain. Accumulated task statistics
  // use the original native polygon, and never query heights outside the region.
  for(const [axis,bound,positive] of [[0,h.ground.west,true],[0,h.ground.east-1e-10,false],[1,h.ground.south,true],[1,h.ground.north-1e-10,false]] as const){
    const result:XY[]=[];
    for(let i=0;i<points.length;i++){
      const a=points[i],b=points[(i+1)%points.length],ai=positive?a[axis]>=bound:a[axis]<=bound,bi=positive?b[axis]>=bound:b[axis]<=bound;
      if(ai)result.push(a);
      if(ai!==bi){const t=(bound-a[axis])/(b[axis]-a[axis]);result.push([a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])]);}
    }
    points=result;
  }
  if(points.length<3)return {points:[],clipped:true,raw:original};
  let area=0;for(let i=0;i<points.length;i++){const a=points[i],b=points[(i+1)%points.length];area+=a[0]*b[1]-b[0]*a[1];}
  need(Math.abs(area)>1e-12,'相机覆盖边界面积为零');
  for(const p of points)surface(p,h);
  return {points,raw:original,clipped:original.some(p=>p[0]<h.ground.west||p[0]>=h.ground.east||p[1]<h.ground.south||p[1]>=h.ground.north)};
}

export interface TaskCoverage {taskId:string;kind:string;cells:number[][];seen:number[];grid:null|{west:number;north:number;dx:number;dy:number;columns:number;rows:number};totalCells:number;seenCells:number;contributors:string[];observationMilliseconds:string}
export interface CoverageSnapshot {schemaVersion:1;status:'live';runId:string;cursor:[string,string];simulationTimeMs:string;gridResolutionMeters:20;sampledStates:number;tasks:TaskCoverage[]}
export function validateSnapshot(raw:unknown,runId:string):CoverageSnapshot {
  const s=record(raw,'累计覆盖');need(s.schemaVersion===1&&s.status==='live'&&s.runId===runId,'累计覆盖运行身份不符');
  need(s.gridResolutionMeters===20,'累计覆盖栅格口径不符');
  const decimal=(value:unknown)=>{need(typeof value==='string'&&/^\d{1,21}$/.test(value),'覆盖整数必须为字符串');};
  decimal(s.simulationTimeMs);const cursor=array(s.cursor,'覆盖记录游标');need(cursor.length===2,'覆盖游标无效');cursor.forEach(decimal);
  let count=0;const ids=new Set<string>();
  for(const raw of array(s.tasks,'累计覆盖任务')){
    const t=record(raw,'覆盖任务');decimal(t.taskId);need(!ids.has(t.taskId as string),'重复覆盖任务');ids.add(t.taskId as string);
    need(['PointSearchTask','LineSearchTask','AreaSearchTask'].includes(String(t.kind)),'覆盖任务类型未知');
    const cells=array(t.cells,'覆盖栅格'),seen=array(t.seen,'已覆盖栅格');count+=cells.length;need(count<=50000,'累计覆盖显示预算超限');
    need(cells.length===t.totalCells&&seen.length===t.seenCells&&new Set(seen).size===seen.length,'覆盖计数不符');
    need(seen.every(v=>typeof v==='number'&&Number.isInteger(v)&&v>=0&&v<cells.length),'覆盖栅格编号无效');
    for(const c of cells){need(Array.isArray(c)&&(c.length===2||c.length===4)&&c.every(v=>typeof v==='number'&&Number.isFinite(v)),'覆盖栅格坐标无效');need(c[0]>=45&&c[0]<46&&c[1]>=-122&&c[1]<-120,'覆盖栅格越界');}
    decimal(t.observationMilliseconds);array(t.contributors,'覆盖实体').forEach(decimal);
    if(t.kind==='AreaSearchTask'){
      const g=record(t.grid,'区域网格');for(const key of ['west','north','dx','dy','columns','rows'])numeric(g[key],key);
      need(Number(g.dx)>0&&Number(g.dy)>0&&Number(g.columns)*Number(g.rows)<=50000,'区域网格无效');
    }
  }
  need(ids.size<=128,'覆盖任务数超限');return raw as CoverageSnapshot;
}

export function areaRuns(task:TaskCoverage):{west:number;east:number;south:number;north:number}[]{
  const grid=task.grid!;const columns=new Map<number,number[]>();
  for(const i of task.seen){const c=task.cells[i];const values=columns.get(c[2])??[];values.push(c[3]);columns.set(c[2],values);}
  const output:{west:number;east:number;south:number;north:number}[]=[];
  for(const [col,rows] of columns){rows.sort((a,b)=>a-b);let start=rows[0],end=start;
    const emit=()=>output.push({west:grid.west+col*grid.dx,east:grid.west+(col+1)*grid.dx,north:grid.north-start*grid.dy,south:grid.north-(end+1)*grid.dy});
    for(const row of rows.slice(1)){if(row===end+1)end=row;else {emit();start=end=row;}}emit();
  }return output;
}
