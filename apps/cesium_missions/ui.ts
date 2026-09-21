import type { Viewer } from 'cesium';
import { need } from '../state/protocol.js';
import type { ReadOnlyConnection } from '../state/connection.js';
import type { EntityConfig, EntityLayer } from '../entities/layer.js';
import { MissionModel, type Category } from './model.js';
import { MissionLayer } from './layer.js';
import type { GroundConfig } from './geometry.js';
import './style.css';

const categories:Record<Category,string>={plans:'完整规划',commands:'当前命令',execution:'执行目标／航段',tasks:'搜索任务',zones:'区域边界'};
const node=<K extends keyof HTMLElementTagNameMap>(tag:K,text?:string)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
export class MissionPanel {
  private readonly panel=node('section');private readonly details=node('section');private readonly list=node('div');
  private readonly error=node('p');private readonly filter=node('select');private readonly pager=node('span');
  private readonly entityFilter=node('input');private page=0;private listSignature='';private detailSignature='';
  private generation=-1;private sequence:string|null=null;private disposed=false;
  readonly layer:MissionLayer;
  private constructor(readonly viewer:Viewer,readonly connection:ReadOnlyConnection,readonly entities:EntityLayer,readonly model:MissionModel){
    this.layer=new MissionLayer(viewer,model,()=>this.render());
    const stack=node('div');stack.id='left-stack';
    const map=node('details'),summary=node('summary','底图与地形');map.append(summary,document.querySelector('aside')!);
    stack.append(map,document.getElementById('entity-panel')!);document.body.append(stack);
    this.panel.id='mission-panel';this.panel.append(node('h2','航线、任务与区域'));stack.append(this.panel);
    const switches=node('div');switches.className='mission-switches';
    for(const [key,title] of Object.entries(categories)){
      const label=node('label'),input=node('input');input.type='checkbox';input.checked=true;input.dataset.layer=key;
      input.onchange=()=>{this.layer.visible[key as Category]=input.checked;this.layer.refreshVisibility();};label.append(input,document.createTextNode(title));switches.append(label);
      const option=node('option',title);option.value=key;this.filter.append(option);
    }
    this.filter.id='mission-category';this.filter.value='tasks';this.filter.setAttribute('aria-label','业务对象类别');this.filter.onchange=()=>{this.page=0;this.render();};
    const wp=node('label'),toggle=node('input');toggle.type='checkbox';toggle.id='waypoint-toggle';toggle.onchange=()=>{this.layer.showWaypoints=toggle.checked;this.layer.refreshVisibility();};wp.append(toggle,document.createTextNode('全部航点'));switches.append(wp);
    this.entityFilter.id='mission-entity-filter';this.entityFilter.type='text';this.entityFilter.placeholder='按关联实体 ID 筛选';this.entityFilter.setAttribute('aria-label','按关联实体 ID 筛选');this.entityFilter.oninput=()=>{this.page=0;this.render();};
    this.list.id='mission-list';this.error.id='mission-error';this.error.setAttribute('role','status');
    const nav=node('div');nav.className='actions';for(const [label,step] of [['上一页',-1],['下一页',1]] as const){const b=node('button',label);b.onclick=()=>{this.page=Math.max(0,this.page+step);this.render();};nav.append(b);}nav.append(this.pager);
    this.panel.append(switches,this.filter,this.entityFilter,this.error,this.list,nav,node('p','虚线：完整规划 · 橙线：当前命令 · 绿线：有推进证据的航段。任务完成后保留对象。'));
    this.details.id='mission-details';document.getElementById('backend-panel')!.append(this.details);
    Object.assign(window,{__g5Missions:{inspect:()=>structuredClone({...this.layer.inspect(),generation:this.generation,sequence:this.sequence,groundSHA256:model.heights.ground.sha256})}});
    this.render();
  }
  static async create(viewer:Viewer,connection:ReadOnlyConnection,entities:EntityLayer,config:EntityConfig):Promise<MissionPanel>{
    const response=await fetch('/missions/runtime.json',{cache:'no-store'});need(response.ok,'业务地理配置缺失');
    const settings=await response.json() as {schemaVersion:number;ground:GroundConfig;maximumVertices:number;rendering:{msaaSamples:number;fxaa:boolean}};need(settings.schemaVersion===1,'业务配置版本无效');
    need(settings.rendering.msaaSamples===1&&settings.rendering.fxaa===true,'抗锯齿配置未通过本轮验证');
    const r=await fetch(settings.ground.url,{cache:'no-store'});need(r.ok,'同源正高栅格缺失');const buffer=await r.arrayBuffer();
    need(buffer.byteLength===settings.ground.width*settings.ground.height*4,'同源地形长度不符');
    const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))].map(n=>n.toString(16).padStart(2,'0')).join('');need(digest===settings.ground.sha256,'同源地形摘要不符');
    const values=new Float32Array(buffer);need(values.every(Number.isFinite),'同源地形无效');
    // Intel/ANGLE D3D11 retained old silhouette stencil footprints with MSAA=4
    // after model shrink (also reproduced with the frozen T06 viewer). Use public
    // single-sample + FXAA controls; no engine patch or driver/global setting.
    viewer.scene.msaaSamples=settings.rendering.msaaSamples;
    viewer.scene.postProcessStages.fxaa.enabled=settings.rendering.fxaa;
    return new MissionPanel(viewer,connection,entities,new MissionModel({geoid:config.height,ground:settings.ground,values},settings.maximumVertices));
  }
  update(){
    if(this.disposed)return;
    if(this.generation!==this.connection.store.generation||this.connection.phase!=='live'){
      this.layer.clear();this.model.clear();this.generation=this.connection.store.generation;this.sequence=null;
    }
    if(this.connection.phase==='live'&&this.sequence!==this.connection.store.identity?.sequence){
      this.model.update(this.connection.store.state);this.layer.update();this.sequence=this.connection.store.identity!.sequence;
    }
    this.render();
  }
  private render(){
    const all=[...this.model.features.values()],wanted=this.entityFilter.value.trim();
    const values=all.filter(f=>f.category===this.filter.value&&(!wanted||f.entityIds.includes(wanted)));
    this.page=Math.min(this.page,Math.max(0,Math.ceil(values.length/30)-1));this.pager.textContent=(this.page+1)+' / '+Math.max(1,Math.ceil(values.length/30));
    const selected=this.layer.selected,list=values.slice(this.page*30,(this.page+1)*30),signature=JSON.stringify(list.map(f=>[f.key,f.status,f.error]))+selected;
    if(signature!==this.listSignature){this.listSignature=signature;this.list.replaceChildren();for(const f of list){const button=node('button',f.title+' · '+f.status);button.dataset.feature=f.key;button.setAttribute('aria-pressed',String(selected===f.key));button.onclick=()=>this.layer.select(f.key);this.list.append(button);}if(!list.length)this.list.append(node('p',this.connection.phase==='live'?'当前没有此类对象':'等待同连接快照恢复'));}
    const errors=all.filter(f=>f.error);this.error.textContent=errors.length?errors.length+' 个对象显示未确认；选中查看原因':'';
    const f=selected&&this.model.features.get(selected),detailSignature=JSON.stringify([f,this.layer.waypoint]);if(detailSignature===this.detailSignature)return;this.detailSignature=detailSignature;this.details.replaceChildren();
    if(!f)return;
    this.details.append(node('hr'),node('h2',f.title));const status=node('p',f.status);status.dataset.missionStatus='true';this.details.append(status);
    if(f.error)this.details.append(node('p',f.error));
    const dl=node('dl'),fields:[string,string][]=[...f.details,['关联实体',f.entityIds.join('、')||'未指定'],['关联任务',f.taskIds.join('、')||'无']];
    const w=this.layer.waypoint&&f.waypoints?.find(w=>w.id===this.layer.waypoint);
    if(w)fields.push(['航点',w.id],['下一航点',w.next],['经纬度',w.vertex.longitude.toFixed(7)+'° / '+w.vertex.latitude.toFixed(7)+'°'],['正高／椭球高',w.vertex.msl.toFixed(2)+' / '+w.vertex.ellipsoid.toFixed(2)+' m'],['原高度',String(w.raw.Altitude)+' m '+(w.raw.AltitudeType===0?'AGL':'MSL／EGM96')],['速度',String(w.raw.Speed)+' m/s（类型 '+String(w.raw.SpeedType)+'）'],['航点关联任务',w.taskIds.join('、')||'无']);
    for(const [name,value] of fields)dl.append(node('dt',name),node('dd',value));this.details.append(dl);
    const actions=node('div');actions.className='actions';const locate=node('button','定位对象');locate.id='mission-locate';locate.onclick=()=>this.layer.locate();actions.append(locate);
    for(const entity of f.entityIds){const b=node('button','实体 '+entity);b.dataset.relatedEntity=entity;b.disabled=!this.entities.objects.has(entity);b.onclick=()=>this.entities.select(entity);actions.append(b);}
    for(const key of f.related){const target=this.model.features.get(key);const b=node('button',target?.title??'缺失 '+key);b.dataset.relatedFeature=key;b.disabled=!target;b.onclick=()=>this.layer.select(key);actions.append(b);}this.details.append(actions);
    if(f.waypoints){const label=node('label','查询航点编号'),input=node('input'),button=node('button','查询航点');input.id='waypoint-query';input.type='text';input.setAttribute('aria-label','航点编号');button.id='waypoint-query-button';button.onclick=()=>{const value=input.value.trim();if(f.waypoints!.some(w=>w.id===value))this.layer.select(f.key,value);else input.setCustomValidity('该航点不在此条航线中');input.reportValidity();};label.append(input);this.details.append(label,button);}
    const provenance=node('details'),pre=node('pre');provenance.append(node('summary','消息来源'));pre.textContent=JSON.stringify(f.source,null,2);provenance.append(pre);this.details.append(provenance);
  }
  destroy(){this.disposed=true;Object.assign(window,{__g5Missions:undefined});this.layer.destroy();this.model.clear();this.panel.remove();this.details.remove();}
}
