import { ArcType, BoundingSphere, CallbackProperty, CameraEventType, Cartesian3, Color, CustomDataSource, HeadingPitchRange, HeightReference, PolygonHierarchy, Rectangle, type Viewer } from 'cesium';
import { type ReadOnlyConnection } from '../state/connection.js';
import { need, type ObjectValue } from '../state/protocol.js';
import { type EntityLayer } from '../entities/layer.js';
import { surface, type Heights, type XY } from '../missions/geometry.js';
import { areaRuns, footprint, validateSnapshot, type CoverageSnapshot, type TaskCoverage } from './geometry.js';
import './style.css';

const node=<K extends keyof HTMLElementTagNameMap>(tag:K,text?:string)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
const green=Color.fromCssColorString('#65ff85');
export class CoveragePanel {
  readonly current=new CustomDataSource('当前传感器覆盖');readonly accumulated=new CustomDataSource('累计侦察覆盖');
  private readonly panel=node('section');private readonly status=node('p');private readonly list=node('div');
  private readonly currentToggle=node('input');private readonly accumulatedToggle=node('input');
  private readonly cameraHint=node('p','左键拖动：缩放；右键拖动：平移／环绕。左键点击选择目标；滚轮缩放，中键转动视角。');
  private generation=-1;private phase='';private disposed=false;private timer:number;
  private inflight=false;private abort:AbortController|null=null;private epoch=0;private signature='';
  private polygons=new Map<string,{points:XY[];raw:XY[];time:string;clipped:boolean;entity:string}>();
  private signatures=new Map<string,string>();private errors:string[]=[];private snapshot:CoverageSnapshot|null=null;
  constructor(readonly viewer:Viewer,readonly connection:ReadOnlyConnection,readonly entities:EntityLayer,readonly heights:Heights){
    // Swap plain drags only; Viewer click selection and modified gestures stay intact.
    const camera=viewer.scene.screenSpaceCameraController;
    camera.translateEventTypes=CameraEventType.RIGHT_DRAG;
    camera.rotateEventTypes=CameraEventType.RIGHT_DRAG;
    camera.zoomEventTypes=[CameraEventType.LEFT_DRAG,CameraEventType.WHEEL,CameraEventType.PINCH];
    this.cameraHint.id='camera-controls-hint';this.cameraHint.className='hint';document.getElementById('entity-panel')!.append(this.cameraHint);
    viewer.dataSources.add(this.current);viewer.dataSources.add(this.accumulated);
    this.panel.id='coverage-panel';this.panel.append(node('h2','侦察覆盖'));
    for(const [input,id,text,source] of [[this.currentToggle,'coverage-current','当前传感器覆盖',this.current],[this.accumulatedToggle,'coverage-accumulated','累计侦察覆盖',this.accumulated]] as const){
      input.type='checkbox';input.id=id;input.checked=true;
      try{const saved=localStorage.getItem(id);if(saved==='false')input.checked=false;}catch{}
      source.show=input.checked;input.onchange=()=>{source.show=input.checked;try{localStorage.setItem(id,String(input.checked));}catch{}viewer.scene.requestRender();};
      const label=node('label');label.append(input,document.createTextNode(text));this.panel.append(label);
    }
    this.status.id='coverage-status';this.list.id='coverage-list';this.panel.append(this.status,this.list,node('p','阵营色：相机当前覆盖；绿色：任务内累计已侦察范围。关闭图层仍继续累计，刷新后恢复。'));
    document.getElementById('left-stack')!.insertBefore(this.panel,document.getElementById('mission-panel'));
    Object.assign(window,{__g5Coverage:{inspect:()=>this.inspect()}});
    this.timer=window.setInterval(()=>{void this.poll();},750);this.update();void this.poll();
  }
  private world(p:XY){const v=surface(p,this.heights);return Cartesian3.fromDegrees(v.longitude,v.latitude,v.ellipsoid);}
  private clear(source:CustomDataSource){if(!this.viewer.isDestroyed()&&this.viewer.selectedEntity&&source.entities.contains(this.viewer.selectedEntity))this.viewer.selectedEntity=undefined;source.entities.removeAll();}
  update(){
    if(this.disposed||this.viewer.isDestroyed())return;
    if(this.generation!==this.connection.store.generation||this.connection.phase!==this.phase){
      this.epoch++;this.abort?.abort();this.clear(this.current);this.clear(this.accumulated);this.polygons.clear();this.signatures.clear();this.snapshot=null;this.signature='';this.list.replaceChildren();
      this.generation=this.connection.store.generation;this.phase=this.connection.phase;
    }
    if(this.phase!=='live'){this.status.textContent='等待后端恢复；旧覆盖已清理';return;}
    const keep=new Set<string>();this.errors=[];
    for(const [id,entity] of Object.entries(this.connection.store.state.entities)){
      const state=entity.state as ObjectValue|undefined;const payloads=state?.PayloadStateList;
      if(!Array.isArray(payloads))continue;
      for(const raw of payloads){
        const sensor=raw as ObjectValue;if(sensor?._type!=='afrl.cmasi.CameraState')continue;
        const key=id+':'+String(sensor.PayloadID);keep.add(key);
        try{
          const signature=JSON.stringify([sensor.Footprint,entity.simulation_time_ms]);if(this.signatures.get(key)===signature)continue;
          this.signatures.set(key,signature);const shape=footprint(sensor.Footprint,this.heights);
          this.current.entities.removeById('sensor:'+key);this.current.entities.removeById('sensor-edge:'+key);this.polygons.delete(key);
          if(!shape.points.length)continue;
          const color=Color.fromCssColorString(this.entities.affiliations.get(id)?.color??'#ffff50'),positions=shape.points.map(p=>this.world(p));
          this.current.entities.add({id:'sensor:'+key,name:'实体 '+id+' · 当前传感器覆盖',polygon:{hierarchy:new PolygonHierarchy(positions),material:color.withAlpha(.18),heightReference:HeightReference.CLAMP_TO_GROUND,arcType:ArcType.GEODESIC}});
          const outline=[...positions,positions[0]];
          this.current.entities.add({id:'sensor-edge:'+key,name:'实体 '+id+' · 覆盖边界',polyline:{positions:new CallbackProperty(()=>outline,false),width:2,material:color,clampToGround:true}});
          this.polygons.set(key,{...shape,time:String(entity.simulation_time_ms),entity:id});
        }catch(error){this.current.entities.removeById('sensor:'+key);this.current.entities.removeById('sensor-edge:'+key);this.polygons.delete(key);this.signatures.delete(key);this.errors.push('实体 '+id+'：'+String(error));}
      }
    }
    for(const key of this.signatures.keys())if(!keep.has(key)){this.current.entities.removeById('sensor:'+key);this.current.entities.removeById('sensor-edge:'+key);this.polygons.delete(key);this.signatures.delete(key);}
    this.describe();
  }
  private describe(){
    if(this.phase!=='live')return;
    const clipped=[...this.polygons.values()].some(p=>p.clipped);
    this.status.textContent=this.errors.length?this.errors.join('；'):this.snapshot?'累计截至 '+(Number(this.snapshot.simulationTimeMs)/1000).toFixed(2)+' 秒 · 当前相机 '+this.polygons.size+' 个'+(clipped?'；越界视场仅显示合格地形内部分':''):'当前相机 '+this.polygons.size+' 个；累计覆盖恢复中';
  }
  private async poll(){
    if(this.disposed||this.inflight||this.connection.phase!=='live')return;
    const epoch=this.epoch,runId=this.connection.store.identity!.run_id;
    this.inflight=true;const abort=new AbortController();this.abort=abort;const timer=window.setTimeout(()=>abort.abort(),4000);
    try{
      const response=await fetch('/api/coverage/v1/snapshot',{cache:'no-store',signal:abort.signal});need(response.ok,'累计覆盖暂不可用，等待恢复');
      const text=await response.text();need(new TextEncoder().encode(text).length<=8388608,'累计覆盖响应超限');
      const snapshot=validateSnapshot(JSON.parse(text),runId);
      if(this.disposed||epoch!==this.epoch||this.connection.phase!=='live'||this.connection.store.identity?.run_id!==runId)return;
      // Never show future cumulative observations relative to the authoritative clock.
      if(BigInt(snapshot.simulationTimeMs)>BigInt(String(this.connection.store.state.simulation.simulation_time_ms)))return;
      this.snapshot=snapshot;
      const signature=JSON.stringify(snapshot.tasks.map(t=>[t.taskId,t.cells,t.seen,t.observationMilliseconds]));
      if(signature!==this.signature){this.signature=signature;this.render(snapshot.tasks);}
      this.describe();
    }catch(error){if(!this.disposed&&epoch===this.epoch&&this.connection.phase==='live'){this.snapshot=null;this.signature='';this.clear(this.accumulated);this.list.replaceChildren();this.status.textContent='累计覆盖暂不可用；当前传感器覆盖仍可查看';}}
    finally{window.clearTimeout(timer);this.inflight=false;if(this.abort===abort)this.abort=null;}
  }
  private render(tasks:TaskCoverage[]){
    this.clear(this.accumulated);this.list.replaceChildren();
    for(const task of tasks){
      const title='任务 '+task.taskId+' · '+(task.kind==='PointSearchTask'?'观察 '+(Number(task.observationMilliseconds)/1000).toFixed(2)+' 秒':task.seenCells+' / '+task.totalCells+'（'+(100*task.seenCells/task.totalCells).toFixed(1)+'%）');
      const row=node('div'),button=node('button',title);button.onclick=()=>this.locate(task);row.append(button);this.list.append(row);
      if(task.kind==='AreaSearchTask')for(const [i,r] of areaRuns(task).entries())this.accumulated.entities.add({id:'coverage:'+task.taskId+':'+i,name:title,rectangle:{coordinates:Rectangle.fromDegrees(r.west,r.south,r.east,r.north),material:green.withAlpha(.43),heightReference:HeightReference.CLAMP_TO_GROUND}});
      else if(task.kind==='LineSearchTask'){
        let positions:Cartesian3[]=[],last:number[]|undefined,index=0;
        const add=()=>{if(positions.length){const saved=positions;this.accumulated.entities.add({id:'coverage:'+task.taskId+':'+index++,name:title,polyline:{positions:new CallbackProperty(()=>saved,false),width:6,material:green,clampToGround:true}});}positions=[];};
        for(const i of task.seen){const c=task.cells[i];if(last&&(Math.abs(last[2]-c[0])>1e-10||Math.abs(last[3]-c[1])>1e-10))add();if(!positions.length)positions.push(this.world([c[1],c[0]]));positions.push(this.world([c[3],c[2]]));last=c;}add();
      }else if(task.seenCells){const c=task.cells[0];this.accumulated.entities.add({id:'coverage:'+task.taskId,name:title,position:this.world([c[1],c[0]]),point:{pixelSize:17,color:green,outlineColor:Color.BLACK,outlineWidth:2,disableDepthTestDistance:Number.POSITIVE_INFINITY}});}
    }
    this.viewer.scene.requestRender();
  }
  private locate(task:TaskCoverage){const points=task.cells.map(c=>this.world([c[1],c[0]]));const sphere=BoundingSphere.fromPoints(points);this.viewer.trackedEntity=undefined;this.viewer.camera.flyToBoundingSphere(sphere,{duration:0,offset:new HeadingPitchRange(0,-Math.PI/3,Math.max(700,sphere.radius*3))});}
  inspect(){return {generation:this.generation,currentVisible:this.current.show,accumulatedVisible:this.accumulated.show,currentObjects:this.current.entities.values.length,accumulatedObjects:this.accumulated.entities.values.length,sensors:Object.fromEntries(this.polygons),snapshot:this.snapshot,status:this.status.textContent};}
  destroy(){this.disposed=true;this.epoch++;window.clearInterval(this.timer);this.abort?.abort();if(!this.viewer.isDestroyed()){this.clear(this.current);this.clear(this.accumulated);this.viewer.dataSources.remove(this.current,true);this.viewer.dataSources.remove(this.accumulated,true);}this.polygons.clear();this.signatures.clear();this.snapshot=null;this.panel.remove();this.cameraHint.remove();Object.assign(window,{__g5Coverage:undefined});}
}
