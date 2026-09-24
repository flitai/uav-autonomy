import {Cartesian2, Cartesian3, Cartographic, Color, HeightReference, Math as CesiumMath, Rectangle,
  ScreenSpaceEventHandler, ScreenSpaceEventType, type Entity, type Viewer} from 'cesium';
import type {Heights} from '../missions/geometry.js';
import {altitude} from '../missions/geometry.js';
import './style.css';

type XY=[number,number];
type Geometry={type:'Point';coordinates:XY}|{type:'LineString';coordinates:XY[]}|{
  type:'Rectangle';center:XY;widthMeters:number;heightMeters:number;rotationDegrees:0};
type Kind='point'|'line'|'area';
type Identity={runId:string;segmentId:string;backendRunId:string;streamId:string};
type Draft={draftId:string;revision:string;kind:Kind;taskId:string;candidateEntityIds:string[];
  geometry:Geometry;runId:string;segmentId:string};
type Route={vehicleId:string;taskId:string;waypointCount:number;waypoints:{longitude:number;latitude:number;altitudeMeters:number}[]};
type Plan={planId:string;taskId:string;revision:string;route:Route;confirmationEnabled:boolean};
type Item={draft:Draft;preview:Plan|null};
type Catalog={contractId:string;altitudeDatum:string;terrainBounds:{west:number;south:number;east:number;north:number};
  taskTypes:Record<Kind,{baselineTaskId:string;baselineEntityIds:string[]}>;limits:{draftCount:number;linePointCount:[number,number]};identity:Identity};

const API='http://127.0.0.1:8003/api/tasks/v1';
const names:Record<Kind,string>={point:'点搜索',line:'折线搜索',area:'矩形区域'};
const exact=(value:string):number=>{const n=Number(value);if(!value.trim()||!Number.isFinite(n))throw Error('请输入有效数字');return n;};
const format=(point:XY)=>point.map(value=>value.toFixed(7)).join(', ');

export class TaskPanel {
  private root=document.createElement('section');private status=document.createElement('p');
  private list=document.createElement('div');private result=document.createElement('p');
  private kind=document.createElement('select');private entity=document.createElement('select');
  private lon=document.createElement('input');private lat=document.createElement('input');
  private line=document.createElement('textarea');private width=document.createElement('input');private height=document.createElement('input');
  private fields=document.createElement('div');private saveButton=document.createElement('button');
  private copyButton=document.createElement('button');private deleteButton=document.createElement('button');
  private previewButton=document.createElement('button');private drawButton=document.createElement('button');
  private clearButton=document.createElement('button');private drawHint=document.createElement('p');
  private catalog:Catalog|null=null;private items:Item[]=[];private selected:string|null=null;
  private dirty=false;private busy=false;private drawing=false;private rectangleStart:XY|null=null;
  private epoch=0;
  private timer:number|undefined;private stopped=false;private previewEntity:Entity|null=null;
  private draftEntity:Entity|null=null;private readonly handler:ScreenSpaceEventHandler;

  constructor(private viewer:Viewer,private heights:Heights){
    this.root.id='task-editor';this.root.setAttribute('aria-label','任务草稿');
    const title=document.createElement('h2');title.textContent='任务草稿';
    const note=document.createElement('p');note.className='hint';note.textContent='首批点、折线、矩形搜索。保存草稿不会改变活动任务。';
    this.status.id='task-status';this.status.setAttribute('role','status');
    const kindLabel=this.label('任务类型',this.kind,'task-kind');
    for(const key of ['point','line','area'] as Kind[]){const option=document.createElement('option');option.value=key;option.textContent=names[key];this.kind.append(option);}
    this.kind.onchange=()=>{this.selected=null;this.clearGeometry();this.markDirty();this.render();};
    const entityLabel=this.label('候选实体',this.entity,'task-entity');
    this.entity.onchange=()=>this.markDirty();
    this.lon.type=this.lat.type=this.width.type=this.height.type='number';
    for(const input of [this.lon,this.lat,this.width,this.height]){input.step='any';input.oninput=()=>this.markDirty();}
    this.lon.value='-120.7645';this.lat.value='45.323';this.width.value='1000';this.height.value='500';
    this.line.rows=5;this.line.placeholder='每行：经度, 纬度';this.line.value='-120.9900, 45.3100\n-120.9800, 45.3200';
    this.line.oninput=()=>this.markDirty();
    const pointFields=document.createElement('div');pointFields.className='task-coordinate-fields';
    pointFields.append(this.label('经度',this.lon,'task-longitude'),this.label('纬度',this.lat,'task-latitude'));
    this.line.id='task-line';const lineLabel=this.label('折线坐标（经度, 纬度）',this.line,'task-line');
    const dimensions=document.createElement('div');dimensions.className='task-coordinate-fields';
    dimensions.append(this.label('宽度 m',this.width,'task-width'),this.label('高度 m',this.height,'task-height'));
    this.fields.append(pointFields,lineLabel,dimensions);
    this.drawButton.id='task-draw';this.drawButton.textContent='地图取点';this.drawButton.onclick=()=>this.toggleDraw();
    this.clearButton.id='task-clear';this.clearButton.textContent='清空几何';this.clearButton.onclick=()=>{this.clearGeometry();this.markDirty();this.render();};
    this.drawHint.className='hint';this.drawHint.textContent='地图取点：点单击一次，折线连续单击，矩形选择两个对角。';
    const drawActions=document.createElement('div');drawActions.className='task-actions';drawActions.append(this.drawButton,this.clearButton);
    this.saveButton.id='task-save';this.saveButton.textContent='保存草稿';this.saveButton.onclick=()=>void this.save();
    this.copyButton.id='task-copy';this.copyButton.textContent='复制';this.copyButton.onclick=()=>void this.copy();
    this.deleteButton.id='task-delete';this.deleteButton.textContent='删除';this.deleteButton.onclick=()=>void this.remove();
    this.previewButton.id='task-preview';this.previewButton.textContent='请求规划预览';this.previewButton.onclick=()=>void this.preview();
    const actions=document.createElement('div');actions.className='task-actions';
    actions.append(this.saveButton,this.copyButton,this.deleteButton,this.previewButton);
    const listTitle=document.createElement('h3');listTitle.textContent='已保存草稿';
    this.list.id='task-drafts';this.result.id='task-result';this.result.setAttribute('role','status');
    this.root.append(title,note,this.status,kindLabel,entityLabel,this.fields,drawActions,this.drawHint,
      actions,listTitle,this.list,this.result);
    document.body.append(this.root);
    this.handler=new ScreenSpaceEventHandler(viewer.canvas);
    this.handler.setInputAction((event:{position:Cartesian2})=>this.mapClick(event.position),ScreenSpaceEventType.LEFT_CLICK);
    Object.assign(window,{__g6Tasks:{inspect:()=>structuredClone(this.inspect())}});
    this.render();void this.poll();
  }

  private label(text:string,control:HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement,id:string){
    control.id=id;const label=document.createElement('label');label.htmlFor=id;label.textContent=text;label.append(control);return label;
  }

  private async api(path:string,method='GET',body?:unknown):Promise<any>{
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),method==='GET'?5000:70000);
    try{
      const reply=await fetch(API+path,{method,headers:body===undefined?undefined:{'Content-Type':'application/json'},
        body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',credentials:'omit',signal:controller.signal});
      const result=await reply.json();
      if(!reply.ok)throw Error(typeof result.detail==='string'?result.detail:`HTTP ${reply.status}`);
      return result;
    }finally{clearTimeout(timer);}
  }

  private async poll(){
    if(this.stopped)return;
    if(this.busy){this.timer=window.setTimeout(()=>void this.poll(),500);return;}
    const epoch=this.epoch;
    try{
      const catalog=await this.api('/catalog') as Catalog;
      const rows=await this.api('/drafts') as {identity:Identity;items:Item[]};
      if(this.busy||epoch!==this.epoch)return;
      if((['runId','segmentId','backendRunId','streamId'] as const).some(key=>
        catalog.identity[key]!==rows.identity[key]))throw Error('草稿运行身份不一致');
      if(this.catalog&&this.catalog.identity.segmentId!==catalog.identity.segmentId){this.selected=null;this.dirty=false;this.clearOverlays();}
      this.catalog=catalog;this.items=rows.items;
      this.status.textContent=`初始状态可编辑 · ${this.items.length}/${catalog.limits.draftCount} 份草稿`;
      if(this.selected&&!this.items.some(item=>item.draft.draftId===this.selected))this.selected=null;
    }catch(error){if(!this.busy&&epoch===this.epoch){this.catalog=null;this.items=[];this.status.textContent='任务服务不可用：'+String(error);}}
    finally{this.render();if(!this.stopped)this.timer=window.setTimeout(()=>void this.poll(),2000);}
  }

  private markDirty(){this.dirty=true;this.showGeometry();this.render();}
  private clearGeometry(){this.rectangleStart=null;this.lon.value='';this.lat.value='';this.line.value='';this.width.value='';this.height.value='';this.clearOverlays();}
  private current():Item|null{return this.items.find(item=>item.draft.draftId===this.selected)??null;}
  private geometry():Geometry{
    const kind=this.kind.value as Kind;
    if(kind==='line'){
      const coordinates=this.line.value.split(/\r?\n/).filter(v=>v.trim()).map(row=>{
        const fields=row.split(',');if(fields.length!==2)throw Error('折线每行应为经度, 纬度');
        return [exact(fields[0]),exact(fields[1])] as XY;});
      if(coordinates.length<2||coordinates.length>128)throw Error('折线需 2～128 个点');
      return {type:'LineString',coordinates};
    }
    const center:XY=[exact(this.lon.value),exact(this.lat.value)];
    return kind==='point'?{type:'Point',coordinates:center}:{type:'Rectangle',center,
      widthMeters:exact(this.width.value),heightMeters:exact(this.height.value),rotationDegrees:0};
  }

  private check(geometry:Geometry){
    const b=this.catalog?.terrainBounds;if(!b)throw Error('地形资格尚未就绪');
    const point=(p:XY)=>{if(p[0]<b.west||p[0]>b.east||p[1]<b.south||p[1]>b.north)
      throw Error('几何超出已验收地形区域');};
    if(geometry.type==='Point')point(geometry.coordinates);
    else if(geometry.type==='LineString')geometry.coordinates.forEach(point);
    else{point(geometry.center);if(geometry.widthMeters<100||geometry.widthMeters>2000||
      geometry.heightMeters<100||geometry.heightMeters>2000)throw Error('矩形宽高需 100～2000 米');}
  }

  private payload(){
    const catalog=this.catalog;if(!catalog)throw Error('任务服务未就绪');
    const kind=this.kind.value as Kind,task=catalog.taskTypes[kind],geometry=this.geometry();this.check(geometry);
    return {...catalog.identity,idempotencyKey:crypto.randomUUID(),kind,geometry,
      candidateEntityIds:[this.entity.value||task.baselineEntityIds[0]],altitudeDatum:catalog.altitudeDatum};
  }

  private async mutate(action:()=>Promise<any>){
    if(this.busy)return;this.busy=true;this.epoch++;this.render();
    try{const result=await action();this.selected=result.draft.draft.draftId;this.dirty=false;
      const index=this.items.findIndex(item=>item.draft.draftId===this.selected);
      if(result.action==='delete')this.items=this.items.filter(item=>item.draft.draftId!==this.selected);
      else if(index>=0)this.items[index]=result.draft;
      else this.items.push(result.draft);
      this.result.textContent=`${{create:'已保存',update:'已更新',copy:'已复制',delete:'已删除',preview:'预览已返回'}[result.action as string]??result.action} · 修订 ${result.draft.draft.revision}`;
      if(result.action==='delete'){this.selected=null;this.clearOverlays();}
      else if(result.action==='preview')this.showPlan(result.draft.preview);
    }catch(error){this.result.textContent='操作未完成：'+String(error)+'。若响应丢失，请先刷新草稿和操作记录。';}
    finally{this.busy=false;this.render();void this.poll();}
  }

  private async save(){await this.mutate(async()=>{
    const body=this.payload(),item=this.current();
    return item?this.api('/drafts/'+item.draft.draftId,'PUT',
      {...body,expectedRevision:item.draft.revision}):this.api('/drafts','POST',body);
  });}
  private async copy(){const item=this.current();if(!item)return;
    await this.mutate(()=>this.api('/drafts/'+item.draft.draftId+'/copy','POST',
      {...this.catalog!.identity,idempotencyKey:crypto.randomUUID(),expectedRevision:item.draft.revision}));}
  private async remove(){const item=this.current();if(!item)return;
    await this.mutate(()=>this.api('/drafts/'+item.draft.draftId,'DELETE',
      {...this.catalog!.identity,idempotencyKey:crypto.randomUUID(),expectedRevision:item.draft.revision}));}
  private async preview(){const item=this.current();if(!item||this.dirty)return;
    await this.mutate(()=>this.api('/drafts/'+item.draft.draftId+'/preview','POST',
      {...this.catalog!.identity,idempotencyKey:crypto.randomUUID(),expectedRevision:item.draft.revision}));}

  private select(item:Item){
    this.selected=item.draft.draftId;this.kind.value=item.draft.kind;this.updateEntity();
    this.entity.value=item.draft.candidateEntityIds[0];const geometry=item.draft.geometry;
    if(geometry.type==='Point'){this.lon.value=String(geometry.coordinates[0]);this.lat.value=String(geometry.coordinates[1]);}
    if(geometry.type==='LineString')this.line.value=geometry.coordinates.map(format).join('\n');
    if(geometry.type==='Rectangle'){this.lon.value=String(geometry.center[0]);this.lat.value=String(geometry.center[1]);
      this.width.value=String(geometry.widthMeters);this.height.value=String(geometry.heightMeters);}
    this.dirty=false;this.showGeometry();this.showPlan(item.preview);this.render();
  }

  private updateEntity(){
    const catalog=this.catalog,kind=this.kind.value as Kind;
    this.entity.replaceChildren();
    if(catalog)for(const id of catalog.taskTypes[kind].baselineEntityIds){
      const option=document.createElement('option');option.value=id;option.textContent='实体 '+id;this.entity.append(option);}
  }

  private render(){
    const ready=!!this.catalog&&!this.busy,kind=this.kind.value as Kind,item=this.current();
    this.updateEntity();if(item&&item.draft.kind===kind)this.entity.value=item.draft.candidateEntityIds[0];
    this.lon.parentElement!.hidden=kind==='line';this.lat.parentElement!.hidden=kind==='line';
    this.line.parentElement!.hidden=kind!=='line';
    this.width.parentElement!.hidden=this.height.parentElement!.hidden=kind!=='area';
    this.saveButton.disabled=!ready||(!this.dirty&&!!item);
    this.copyButton.disabled=this.deleteButton.disabled=!ready||!item;
    this.previewButton.disabled=!ready||!item||this.dirty;
    this.drawButton.disabled=!ready;
    this.drawButton.textContent=this.drawing?'结束取点':'地图取点';
    this.list.replaceChildren();for(const row of this.items){
      const button=document.createElement('button');button.textContent=`${names[row.draft.kind]} · 实体 ${row.draft.candidateEntityIds[0]} · 修订 ${row.draft.revision}`;
      button.dataset.draftId=row.draft.draftId;button.setAttribute('aria-pressed',String(this.selected===row.draft.draftId));
      button.onclick=()=>this.select(row);this.list.append(button);}
  }

  private toggleDraw(){this.drawing=!this.drawing;this.rectangleStart=null;this.render();}
  private mapClick(position:Cartesian2){
    if(!this.drawing||!this.catalog||this.busy)return;
    const ray=this.viewer.camera.getPickRay(position);
    const world=(ray&&this.viewer.scene.globe.pick(ray,this.viewer.scene))||this.viewer.camera.pickEllipsoid(position);
    if(!world)return;
    const c=Cartographic.fromCartesian(world),point:XY=[CesiumMath.toDegrees(c.longitude),CesiumMath.toDegrees(c.latitude)];
    const b=this.catalog.terrainBounds;
    if(point[0]<b.west||point[0]>b.east||point[1]<b.south||point[1]>b.north){this.result.textContent='地图取点超出已验收地形区域';return;}
    const kind=this.kind.value as Kind;
    if(kind==='line')this.line.value+=(this.line.value.trim()?'\n':'')+format(point);
    else if(kind==='point'){this.lon.value=String(point[0]);this.lat.value=String(point[1]);this.drawing=false;}
    else if(!this.rectangleStart){this.rectangleStart=point;this.result.textContent='已选择矩形第一角，请选择对角';return;}
    else{
      const first=this.rectangleStart;this.rectangleStart=null;
      const center:XY=[(first[0]+point[0])/2,(first[1]+point[1])/2];
      this.lon.value=String(center[0]);this.lat.value=String(center[1]);
      this.width.value=String(Math.round(Math.abs(point[0]-first[0])*111320*Math.cos(CesiumMath.toRadians(center[1]))));
      this.height.value=String(Math.round(Math.abs(point[1]-first[1])*111320));this.drawing=false;
    }
    this.markDirty();
  }

  private clearOverlays(){if(this.draftEntity)this.viewer.entities.remove(this.draftEntity);
    if(this.previewEntity)this.viewer.entities.remove(this.previewEntity);
    this.draftEntity=this.previewEntity=null;this.viewer.scene.requestRender();}
  private showGeometry(){
    if(this.draftEntity){this.viewer.entities.remove(this.draftEntity);this.draftEntity=null;}
    try{const geometry=this.geometry();
      if(geometry.type==='Point')this.draftEntity=this.viewer.entities.add({name:'草稿点',position:Cartesian3.fromDegrees(...geometry.coordinates),
        point:{pixelSize:12,color:Color.CYAN,heightReference:HeightReference.CLAMP_TO_GROUND}});
      else if(geometry.type==='LineString'&&geometry.coordinates.length>=2)this.draftEntity=this.viewer.entities.add({name:'草稿折线',
        polyline:{positions:geometry.coordinates.map(p=>Cartesian3.fromDegrees(...p)),width:3,material:Color.CYAN,clampToGround:true}});
      else if(geometry.type==='Rectangle'){
        const halfLon=geometry.widthMeters/(2*111320*Math.cos(CesiumMath.toRadians(geometry.center[1])));
        const halfLat=geometry.heightMeters/(2*111320);
        this.draftEntity=this.viewer.entities.add({name:'草稿矩形',rectangle:{coordinates:Rectangle.fromDegrees(
          geometry.center[0]-halfLon,geometry.center[1]-halfLat,geometry.center[0]+halfLon,geometry.center[1]+halfLat),
          fill:false,outline:true,outlineColor:Color.CYAN}});}
    }catch{/* Incomplete numeric editing is shown by the input fields; the server validates on save. */}
    this.viewer.scene.requestRender();
  }
  private showPlan(plan:Plan|null){
    if(this.previewEntity){this.viewer.entities.remove(this.previewEntity);this.previewEntity=null;}
    if(plan&&plan.route.waypoints.length>=2){
      const positions=plan.route.waypoints.map(w=>{
        const vertex=altitude([w.longitude,w.latitude],w.altitudeMeters,1,this.heights);
        return Cartesian3.fromDegrees(vertex.longitude,vertex.latitude,vertex.ellipsoid);});
      this.previewEntity=this.viewer.entities.add({name:'隔离规划预览',polyline:{positions,width:4,material:Color.YELLOW}});
      this.result.textContent=`仅预览 · 实体 ${plan.route.vehicleId} · ${plan.route.waypointCount} 航点 · 未下发`;
    }
    this.viewer.scene.requestRender();
  }

  inspect(){return {ready:!!this.catalog,selected:this.selected,dirty:this.dirty,drawing:this.drawing,
    items:this.items.map(item=>({draft:item.draft,planId:item.preview?.planId??null})),
    previewVisible:!!this.previewEntity,result:this.result.textContent};}
  destroy(){this.stopped=true;clearTimeout(this.timer);this.handler.destroy();this.clearOverlays();
    Object.assign(window,{__g6Tasks:undefined});this.root.remove();}
}
