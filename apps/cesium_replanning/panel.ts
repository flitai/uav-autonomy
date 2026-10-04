import './style.css';

type Identity={runId:string;segmentId:string;backendRunId:string;streamId:string};
type Draft={draftId:string;revision:string;taskId:string;kind:string;
  geometry:Record<string,unknown>};
type Task={taskId:string;kind:string;draft:Draft};
type State={identity:Identity;status:string;simulation:null|{simulation_time_ms:string};
  originalTasks:Task[];availableDrafts:Draft[];switch:null|{status:string;key:string;
    taskStages?:{taskId:string;status:string}[]}};
type Review={planId:string;identity:Identity;reviewSHA256:string;pausedAtMs:string;
  change:{action:string};oldCoverage:{taskId:string;kind:string;seenCells:number;totalCells:number;
    observationMilliseconds:string}[];
  tasks:{taskId:string;oldTaskId:string;kind:string;revision:string}[];
  plan:{assignments:{taskId:string;vehicleId:string;estimatedCompletionMs:string}[];
    commands:{vehicleId:string;taskIds:string[];waypoints:{number:string;longitude:number;
      latitude:number;altitudeMeters:number;taskIds:string[]}[];
      timeBudget:{routeMeters:number;requiredBudgetSeconds:number;availableSeconds:number}}[]};
  differences:{vehicleId:string;oldWaypointCount:number;newWaypointCount:number;
    oldRouteMeters:number;newRouteMeters:number}[];confirmationAllowed:boolean};

const BASE='http://127.0.0.1:8006/api/tasks/v3';
const LABEL:Record<string,string>={line:'线搜索',point:'点搜索',area:'矩形搜索'};

export class ReplanningPanel {
  private root=document.createElement('details');
  private intro=document.createElement('p');
  private action=document.createElement('select');
  private target=document.createElement('select');
  private editor=document.createElement('div');
  private planButton=document.createElement('button');
  private reviewBox=document.createElement('div');
  private acknowledge=document.createElement('input');
  private ackLabel=document.createElement('label');
  private confirmButton=document.createElement('button');
  private status=document.createElement('p');
  private state:State|null=null;
  private review:Review|null=null;
  private key:string|null=null;
  private busy=false;
  private stopped=false;
  private timer:number|undefined;
  private signature='';

  constructor(){
    const page=document.getElementById('workspace-task-page');
    if(!page)throw Error('任务工作区尚未初始化');
    this.root.id='controlled-replanning';
    this.reviewBox.id='replan-review';
    const title=document.createElement('summary');title.textContent='执行中调整任务';
    for(const [value,name] of [['revise','修改任务'],['add','新增任务']]){
      const option=document.createElement('option');option.value=value;option.textContent=name;
      this.action.append(option);
    }
    this.action.id='replan-action';this.action.onchange=()=>{this.invalidate();this.render();};
    this.target.id='replan-target';this.target.onchange=()=>{this.invalidate();this.renderEditor();};
    this.planButton.id='replan-preview';this.planButton.textContent='生成替代方案';
    this.planButton.onclick=()=>void this.plan();
    this.acknowledge.type='checkbox';this.acknowledge.id='replan-ack';
    this.acknowledge.onchange=()=>this.renderButtons();
    this.ackLabel.append(this.acknowledge,
      document.createTextNode('我已核对新任务、航线和原方案切换'));
    this.confirmButton.id='replan-confirm';this.confirmButton.textContent='确认切换并继续仿真';
    this.confirmButton.onclick=()=>void this.confirm();
    this.status.id='replan-status';this.status.setAttribute('role','status');
    this.root.append(title,this.intro,this.action,this.target,this.editor,this.planButton,
      this.reviewBox,this.ackLabel,this.confirmButton,this.status);
    page.prepend(this.root);
    this.render();void this.refresh();this.poll();
    Object.assign(window,{__g6Replanning:{inspect:()=>structuredClone({state:this.state,
      review:this.review,key:this.key,status:this.status.textContent})}});
  }

  private async api(path:string,method='GET',body?:unknown){
    const response=await fetch(BASE+path,{method,cache:'no-store',credentials:'omit',
      headers:body===undefined?undefined:{'Content-Type':'application/json'},
      body:body===undefined?undefined:JSON.stringify(body)});
    const value=await response.json();
    if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:
      typeof value.error==='string'?value.error:`HTTP ${response.status}`);
    return value;
  }

  private async refresh(){
    if(this.busy||this.stopped)return;
    try{
      const state=await this.api('/state') as State;
      const signature=JSON.stringify([state.identity,state.status,state.originalTasks,
        state.availableDrafts,state.switch?.status]);
      if(signature===this.signature)return;
      this.signature=signature;
      if(this.state&&this.state.identity.streamId!==state.identity.streamId){
        this.review=null;this.key=null;this.reviewBox.replaceChildren();
      }
      this.state=state;
      this.render();
      if(state.switch){
        const stages=state.switch.taskStages?.map(task=>`${task.taskId} ${task.status}`).join(' · ');
        this.status.textContent=state.switch.status==='uncertain'?
          '切换结果待核实，请保持当前仿真状态。':
          state.switch.status==='completed'?'替代任务已完成。':
          `替代方案已下发。${stages??''}`;
      }
    }catch{this.status.textContent='任务调整服务暂不可用。';}
  }

  private render(){
    const state=this.state;
    const available=state?.status==='paused'&&!state.switch;
    this.action.hidden=!available;this.target.hidden=!available;
    this.editor.hidden=!available;this.planButton.hidden=!available;
    this.ackLabel.hidden=!this.review||!available;
    this.confirmButton.hidden=!this.review||!available;
    this.intro.textContent=!state?'正在读取仿真状态…':state.switch?
      '本仿真段已提交替代方案。':state.status==='pre-start'?
      '仿真开始并执行任务后，可在这里调整。':state.status==='pause-to-replan'?
      '先暂停仿真，再编辑并生成替代方案。':
      `已暂停于 ${(Number(state.simulation?.simulation_time_ms??0)/1000).toFixed(1)} 秒。`;
    if(!available){this.renderButtons();return;}
    const previous=this.target.value;
    this.target.replaceChildren();
    const tasks=this.action.value==='revise'?state.originalTasks:state.availableDrafts;
    for(const task of tasks){
      const option=document.createElement('option');
      option.value=this.action.value==='revise'?task.taskId:(task as Draft).draftId;
      option.textContent=`${LABEL[task.kind]} · ${task.taskId}`;
      this.target.append(option);
    }
    if([...this.target.options].some(option=>option.value===previous))this.target.value=previous;
    this.target.hidden=tasks.length===0;
    this.planButton.disabled=this.busy||tasks.length===0;
    this.renderEditor();this.renderButtons();
  }

  private renderEditor(){
    this.editor.replaceChildren();
    if(this.action.value!=='revise')return;
    const task=this.state?.originalTasks.find(row=>row.taskId===this.target.value);
    if(!task)return;
    const hint=document.createElement('label');hint.textContent=task.kind==='line'?
      '折线坐标（每行：经度,纬度）':task.kind==='point'?'点坐标（经度,纬度）':
      '矩形中心（经度,纬度）';
    const coordinates=document.createElement('textarea');coordinates.id='replan-coordinates';
    const geometry=task.draft.geometry;
    const points=task.kind==='line'?geometry.coordinates:
      task.kind==='point'?geometry.coordinates:geometry.center;
    coordinates.value=task.kind==='line'?(points as number[][]).map(p=>p.join(',')).join('\n'):
      (points as number[]).join(',');
    coordinates.rows=task.kind==='line'?5:2;
    coordinates.oninput=()=>this.invalidate();
    hint.append(coordinates);this.editor.append(hint);
    if(task.kind==='area'){
      for(const [id,label,value] of [
        ['widthMeters','宽度（米）',geometry.widthMeters],
        ['heightMeters','高度（米）',geometry.heightMeters]]){
        const field=document.createElement('label');field.textContent=String(label);
        const input=document.createElement('input');input.type='number';input.min='100';input.max='2000';
        input.id='replan-'+id;input.value=String(value);input.oninput=()=>this.invalidate();
        field.append(input);this.editor.append(field);
      }
    }
  }

  private geometry(task:Task){
    const raw=(document.getElementById('replan-coordinates') as HTMLTextAreaElement).value;
    const parse=(line:string)=>{
      const values=line.split(',').map(value=>Number(value.trim()));
      if(values.length!==2||values.some(value=>!Number.isFinite(value)))
        throw Error('请填写经度,纬度');
      return values;
    };
    if(task.kind==='line')return {type:'LineString',
      coordinates:raw.split(/\r?\n/).map(line=>line.trim()).filter(Boolean).map(parse)};
    if(task.kind==='point')return {type:'Point',coordinates:parse(raw)};
    return {type:'Rectangle',center:parse(raw),
      widthMeters:Number((document.getElementById('replan-widthMeters') as HTMLInputElement).value),
      heightMeters:Number((document.getElementById('replan-heightMeters') as HTMLInputElement).value),
      rotationDegrees:0};
  }

  private invalidate(){
    this.review=null;this.reviewBox.replaceChildren();this.acknowledge.checked=false;
    this.ackLabel.hidden=true;this.confirmButton.hidden=true;
    this.renderButtons();
  }

  private renderButtons(){
    this.planButton.disabled=this.busy||!this.state||this.state.status!=='paused'||
      !!this.state.switch||this.target.options.length===0;
    this.confirmButton.disabled=this.busy||!this.review||!this.review.confirmationAllowed||
      !this.acknowledge.checked||!!this.key;
  }

  private async plan(){
    const state=this.state;if(!state||this.busy)return;
    this.busy=true;this.status.textContent='正在按暂停时的位置计算替代方案…';this.renderButtons();
    try{
      const change=this.action.value==='revise'?{
        action:'revise',taskId:this.target.value,
        geometry:this.geometry(state.originalTasks.find(task=>task.taskId===this.target.value)!)}:
        {action:'add',draftId:this.target.value};
      const result=await this.api('/plans','POST',{
        ...state.identity,idempotencyKey:crypto.randomUUID(),change}) as {review:Review};
      this.review=result.review;this.acknowledge.checked=false;
      this.showReview(result.review);
      this.status.textContent=result.review.confirmationAllowed?
        '替代方案已生成，请核对后切换。':'剩余仿真时长不足，请调整任务。';
    }catch(error){this.review=null;this.reviewBox.replaceChildren();
      this.status.textContent='替代规划失败：'+String(error);}
    finally{this.busy=false;this.renderButtons();}
  }

  private showReview(review:Review){
    const heading=document.createElement('h3');heading.textContent='替代方案审查';
    const old=document.createElement('p');old.textContent=`原方案：${this.state?.originalTasks.map(t=>t.taskId).join('、')??''}；新版本：${review.tasks.map(t=>`${t.taskId}（修订 ${t.revision}）`).join('、')}`;
    const table=document.createElement('table');
    for(const assignment of review.plan.assignments){
      const row=document.createElement('tr');
      for(const value of [`任务 ${assignment.taskId}`,`飞机 ${assignment.vehicleId}`,
        `预计完成 ${Math.ceil(Number(assignment.estimatedCompletionMs)/1000)} 秒`]){
        const cell=document.createElement('td');cell.textContent=value;row.append(cell);
      }
      table.append(row);
    }
    const changes=document.createElement('div');
    for(const item of review.differences){
      const line=document.createElement('p');
      line.textContent=`飞机 ${item.vehicleId}：${item.oldWaypointCount} → ${item.newWaypointCount} 航点；${(item.oldRouteMeters/1000).toFixed(1)} → ${(item.newRouteMeters/1000).toFixed(1)} km`;
      changes.append(line);
    }
    const coverage=document.createElement('details');
    const title=document.createElement('summary');title.textContent='切换前侦察统计';coverage.append(title);
    for(const item of review.oldCoverage){
      const line=document.createElement('p');
      line.textContent=item.kind==='PointSearchTask'?
        `任务 ${item.taskId}：观察 ${(Number(item.observationMilliseconds)/1000).toFixed(1)} 秒`:
        `任务 ${item.taskId}：${item.seenCells} / ${item.totalCells} 格`;
      coverage.append(line);
    }
    const routes=document.createElement('div');
    for(const command of review.plan.commands){
      const route=document.createElement('details');const title=document.createElement('summary');
      title.textContent=`飞机 ${command.vehicleId} · ${command.waypoints.length} 航点 · ${command.taskIds.join(' → ')}`;
      const list=document.createElement('ol');
      for(const point of command.waypoints){
        const line=document.createElement('li');
        line.textContent=`${point.number} · ${point.longitude.toFixed(6)}, ${point.latitude.toFixed(6)} · ${point.altitudeMeters.toFixed(0)} m · ${point.taskIds.join(', ')}`;
        list.append(line);
      }
      route.append(title,list);routes.append(route);
    }
    this.reviewBox.replaceChildren(heading,old,table,changes,coverage,routes);
    this.ackLabel.hidden=false;this.confirmButton.hidden=false;this.renderButtons();
  }

  private async confirm(){
    const review=this.review;if(!review||this.busy||this.key)return;
    this.busy=true;this.key=crypto.randomUUID();this.renderButtons();
    this.status.textContent='正在切换任务，请勿重复提交。';
    try{
      const receipt=await this.api(`/plans/${review.planId}/confirm`,'POST',{
        ...review.identity,reviewSHA256:review.reviewSHA256,
        idempotencyKey:this.key,acknowledged:true}) as {status:string;error?:string};
      this.status.textContent=receipt.status==='switched'?
        '替代方案已下发，仿真继续运行。':
        `切换结果待核实：${receipt.error??receipt.status}`;
    }catch(error){this.status.textContent='切换结果待核实，请查询本次操作：'+String(error);}
    finally{this.busy=false;this.renderButtons();}
  }

  private poll(){
    if(this.stopped)return;
    if(this.key&&!this.busy){
      void this.api(`/confirmations/${this.key}`).then((receipt:{status:string;
          taskStages?:{taskId:string;status:string}[];error?:string})=>{
        this.status.textContent=receipt.status==='uncertain'?
          '切换结果待核实：'+(receipt.error??'请检查运行记录'):
          receipt.status==='completed'?'替代任务已完成。':
          `替代方案已下发。${receipt.taskStages?.map(t=>`${t.taskId} ${t.status}`).join(' · ')??''}`;
      }).catch(()=>{});
    }
    void this.refresh();
    this.timer=window.setTimeout(()=>this.poll(),2000);
  }

  destroy(){this.stopped=true;if(this.timer!==undefined)clearTimeout(this.timer);
    this.root.remove();delete (window as unknown as Record<string,unknown>).__g6Replanning;}
}
