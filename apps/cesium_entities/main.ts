import { Viewer } from 'cesium';
import { ReadOnlyConnection } from '../state/connection';
import { collections, type Limits } from '../state/protocol';
import { EntityLayer, type EntityConfig } from './layer';
import { position, type Position, requireValue } from './coordinates';
import { validateAffiliations } from './affiliation';
import './style.css';

const phaseNames = {connecting:'正在连接', 'waiting-snapshot':'等待完整快照', live:'已同步', recovering:'恢复中 · 数据已过期', degraded:'后端不可用', ended:'后端已结束', offline:'未连接'};
const panel = document.createElement('section'); panel.id='backend-panel'; panel.setAttribute('aria-label','实体详情');
panel.innerHTML='<h2>仿真连接</h2><p id="backend-status" role="status">正在读取配置…</p><p id="backend-counts"></p><p id="backend-error" role="alert"></p><hr><h2 id="selected-title">实体详情</h2><p id="selected-hint">在实体列表或场景中选择对象</p><dl id="entity-details"></dl><div class="actions"><button id="entity-locate" disabled>定位</button><button id="entity-follow" disabled>跟随</button><button id="entity-reset">视角复位</button></div><p id="entity-error" role="alert"></p>';
document.body.append(panel);
const listPanel=document.createElement('section');listPanel.id='entity-panel';listPanel.setAttribute('aria-label','仿真实体');
listPanel.innerHTML='<h2>仿真实体</h2><label class="check"><input id="entity-toggle" type="checkbox" checked>实体</label><label class="check"><input id="label-toggle" type="checkbox" checked>标签</label><label class="check"><input id="trail-toggle" type="checkbox" checked>实际轨迹</label><div id="entity-list"></div><div id="affiliation-legend" aria-label="阵营颜色图例"></div><p id="model-scale" class="hint">模型屏幕尺寸</p><p class="hint">+ 放大 · − 缩小 · 0 默认尺寸<br>拉近拉远保持模型大小；不代表实际占地。<br>轨迹保留最近 10 分钟；刷新后重新积累。</p>';
document.body.append(listPanel);
const timeElement=document.querySelector('footer span')!;timeElement.id='backend-time';
const text=(id:string,value:string)=>{document.getElementById(id)!.textContent=value;};
const seconds=(v:unknown)=>typeof v==='string'?`${BigInt(v)/1000n}.${(BigInt(v)%1000n).toString().padStart(3,'0')} 秒`:'未连接';

try {
  const get=async(path:string)=>{const r=await fetch(path,{cache:'no-store'});requireValue(r.ok,'本地配置不可用');return r.json();};
  const config=await get('/entities/runtime.json') as EntityConfig;
  validateAffiliations(config.affiliations);
  const legend=document.getElementById('affiliation-legend')!;
  for(const style of Object.values(config.affiliations.styles)){const item=document.createElement('span');item.textContent=style.label;item.style.setProperty('--affiliation-color',style.color);legend.append(item);}
  const stateConfig=await get('/state/runtime.json') as {limits:Limits;schemaVersion:number;protocolVersion:number};
  requireValue(stateConfig.schemaVersion===1&&stateConfig.protocolVersion===1&&config.height.datum==='EGM96','实体运行配置无效');
  let viewer:Viewer|undefined;
  for(let i=0;i<600;i++){viewer=(window as any).__g5Map?.viewer;if(viewer)break;await new Promise(r=>setTimeout(r,50));}
  requireValue(viewer,'地图初始化未完成');
  let layer:EntityLayer;let lastList='';
  const connection=new ReadOnlyConnection(location.origin,stateConfig.limits,()=>layer?.update());
  const render=()=>{
    const value=connection.inspect();document.documentElement.dataset.backendReady=String(value.phase==='live');
    text('backend-status',phaseNames[value.phase]);text('backend-error',value.error);text('entity-error',layer.error);
    text('model-scale',`模型屏幕尺寸 ${Math.round(config.display.sizePixels*layer.modelScale)} px · ${layer.modelScale.toFixed(2).replace(/\.00$/,'')}×`);
    text('backend-counts',collections.map((k,i)=>['实体','任务','航线','命令','区域'][i]+' '+Object.keys(value.state[k]).length).join(' · '));
    const simulation=value.state.simulation;
    timeElement.textContent=value.phase==='live'?`后端时间：${seconds(simulation.simulation_time_ms)} · ${['停止','运行','暂停','重置','未知'][Number(simulation.state)]??''}`:`后端时间：${seconds(value.lastKnownTime)}${value.lastKnownTime===null?'':' · 已过期'}`;
    const ids=[...layer.objects.keys()].sort((a,b)=>BigInt(a)<BigInt(b)?-1:BigInt(a)>BigInt(b)?1:0),listKey=JSON.stringify(ids.map(id=>[id,layer.affiliations.get(id)]))+'|'+layer.selected;
    if(listKey!==lastList){lastList=listKey;const host=document.getElementById('entity-list')!;host.replaceChildren();for(const id of ids){const style=layer.affiliations.get(id)!;const button=document.createElement('button');button.textContent='实体 '+id+' · '+style.label;button.style.setProperty('--affiliation-color',style.color);button.dataset.entityId=id;button.dataset.affiliation=style.key;button.setAttribute('aria-pressed',String(layer.selected===id));button.onclick=()=>layer.select(id);host.append(button);}}
    const selected=layer.selected && value.state.entities[layer.selected];
    for(const id of ['entity-locate','entity-follow'])(document.getElementById(id) as HTMLButtonElement).disabled=!selected;
    text('selected-title',selected?'实体 '+layer.selected:'实体详情');text('selected-hint',selected?(layer.viewer.trackedEntity?'视角跟随中':''):'在实体列表或场景中选择对象');
    const details=document.getElementById('entity-details')!;details.replaceChildren();
    if(selected && selected.position){
      const p=selected.position as unknown as Position,converted=position(p,config.height),attitude=selected.attitude as Record<string,number>,pose=layer.poses.get(layer.selected!)!;
      const fields:[string,string][]=[['经度',p.longitude_deg.toFixed(7)+'°'],['纬度',p.latitude_deg.toFixed(7)+'°'],['正高（EGM96）',p.altitude_m.toFixed(2)+' m'],['椭球高（WGS84）',converted.ellipsoid.toFixed(2)+' m'],['航向 / 俯仰 / 滚转',[attitude.heading_deg,attitude.pitch_deg,attitude.roll_deg].map(x=>x.toFixed(2)+'°').join(' / ')],['源状态时间',seconds(selected.simulation_time_ms)],['显示时间',seconds(pose.time)],['当前命令',String(selected.current_command_id??'—')],['当前航点',String(selected.current_waypoint_id??'—')],['关联任务',Array.isArray(selected.associated_task_ids)?selected.associated_task_ids.join('、'):'—'],['显示模型',config.modelName]];
      const affiliation=layer.affiliations.get(layer.selected!)!;
      fields.unshift(['阵营',affiliation.label],['阵营来源',affiliation.source==='display-config'?'用户指定（后端：'+(affiliation.reported||'未提供')+'）':affiliation.source==='backend'?'后端报告：'+affiliation.reported:affiliation.source==='unmapped'?'后端名称尚未配置颜色':'后端未指定']);
      for(const [label,value] of fields){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;details.append(dt,dd);}
    }
  };
  layer=new EntityLayer(viewer,connection,config,render);
  for(const [id,key] of [['entity-toggle','showModels'],['label-toggle','showLabels'],['trail-toggle','showTrails']] as const){const input=document.getElementById(id) as HTMLInputElement;input.onchange=()=>{layer[key]=input.checked;layer.update();};}
  document.getElementById('entity-locate')!.onclick=()=>layer.locate();document.getElementById('entity-follow')!.onclick=()=>layer.follow();document.getElementById('entity-reset')!.onclick=()=>layer.reset();
  document.getElementById('reset-view')!.addEventListener('click',()=>layer.reset());
  const resize=(event:KeyboardEvent)=>{
    const element=event.target as HTMLElement;
    if(event.ctrlKey||event.metaKey||event.altKey||element?.isContentEditable||['INPUT','TEXTAREA','SELECT'].includes(element?.tagName))return;
    let scale=layer.modelScale;
    if(event.key==='+'||event.key==='='||event.code==='NumpadAdd')scale=Math.min(config.display.maximumScale,scale*Math.SQRT2);
    else if(event.key==='-'||event.code==='NumpadSubtract')scale=Math.max(config.display.minimumScale,scale/Math.SQRT2);
    else if(event.key==='0')scale=1;else return;
    event.preventDefault();layer.modelScale=scale;layer.update();
  };
  window.addEventListener('keydown',resize);
  Object.assign(window,{__g5State:{inspect:()=>structuredClone(connection.inspect()),config:stateConfig},__g5Entities:{inspect:()=>structuredClone(layer.inspect()),config}});
  let disposed=false;
  const dispose=()=>{if(disposed)return;disposed=true;Object.assign(window,{__g5State:undefined,__g5Entities:undefined});window.removeEventListener('keydown',resize);connection.stop();layer.destroy();};
  // T03 owns Viewer destruction in beforeunload. Release entity references first.
  window.addEventListener('beforeunload',dispose,{once:true,capture:true});
  window.addEventListener('pagehide',dispose,{once:true,capture:true});
  connection.start();
}catch(error){text('backend-status','实体显示未就绪');text('backend-error',String(error));document.documentElement.dataset.entityReady='failed';}
