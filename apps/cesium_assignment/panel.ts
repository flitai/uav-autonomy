import './style.css';

type Identity={runId:string;segmentId:string;backendRunId:string;streamId:string};
type Draft={draftId:string;revision:string;taskId:string;kind:string};
type State={identity:Identity;candidates:Record<string,string[]>;drafts:Draft[];
  sequenceVehicleId:string};
type Assignment={taskId:string;vehicleId:string;optionId:string;estimatedCompletionMs:string};
type Point={number:string;longitude:number;latitude:number;altitudeMeters:number;taskIds:string[]};
type Command={vehicleId:string;waypoints:Point[];taskIds:string[];
  timeBudget:{routeMeters:number;requiredBudgetSeconds:number;availableSeconds:number;fits:boolean}};
type Review={planId:string;identity:Identity;relationship:'parallel'|'sequence';taskOrder:string[];
  tasks:{draftId:string;revision:string;taskId:string;kind:string;candidateEntityIds:string[]}[];
  plan:{assignments:Assignment[];commands:Command[];
    candidateInitialCosts:{taskId:string;vehicleId:string;initialTimeToGoMs:string}[];
    timeBudgetFits:boolean};confirmationAllowed:boolean;reviewSHA256:string};
type Receipt={status:string;phase:string;tasks?:{taskId:string;vehicleId:string;status:string}[];
  error?:string};

const BASE='http://127.0.0.1:8005/api/tasks/v2';
const NAMES:Record<string,string>={line:'线搜索',point:'点搜索',area:'矩形搜索'};

export class AssignmentPanel {
  private root=document.createElement('details');
  private editor=document.createElement('details');
  private choices=document.createElement('div');
  private order=document.createElement('div');
  private relation=document.createElement('select');
  private preview=document.createElement('button');
  private review=document.createElement('div');
  private acknowledge=document.createElement('input');
  private ackLabel=document.createElement('label');
  private confirm=document.createElement('button');
  private status=document.createElement('p');
  private state:State|null=null;
  private selected=new Set<string>();
  private candidates=new Map<string,string[]>();
  private taskOrder:string[]=[];
  private current:Review|null=null;
  private confirmationKey:string|null=null;
  private draftSignature='';
  private busy=false;
  private stopped=false;
  private timer:number|undefined;

  constructor(){
    const page=document.getElementById('workspace-task-page');
    if(!page)throw Error('任务工作区尚未初始化');
    this.root.id='multi-task-planning';
    const title=document.createElement('summary');title.textContent='多机多任务规划';
    const intro=document.createElement('p');intro.textContent='先在下方保存至少两个任务草稿，再选择候选飞机和任务关系。';
    for(const [value,label] of [['parallel','自由分配'],['sequence','按顺序执行']]){
      const option=document.createElement('option');option.value=value;option.textContent=label;
      this.relation.append(option);
    }
    this.relation.id='multi-relationship';
    this.relation.onchange=()=>{this.current=null;this.review.replaceChildren();this.render();};
    const relationshipLabel=document.createElement('label');
    relationshipLabel.textContent='任务关系';relationshipLabel.append(this.relation);
    this.preview.id='multi-preview';this.preview.textContent='生成联合方案';
    this.preview.onclick=()=>void this.plan();
    this.acknowledge.type='checkbox';this.acknowledge.id='multi-ack';
    this.acknowledge.onchange=()=>this.render();
    this.ackLabel.htmlFor=this.acknowledge.id;
    this.ackLabel.append(this.acknowledge,document.createTextNode('我已核对任务、分配、顺序和航线'));
    this.confirm.id='multi-confirm';this.confirm.textContent='确认并下发联合方案';
    this.confirm.onclick=()=>void this.activate();
    this.status.id='multi-status';this.status.setAttribute('role','status');
    const editorTitle=document.createElement('summary');editorTitle.textContent='任务与候选飞机';
    this.editor.open=true;
    this.editor.append(editorTitle,this.choices,relationshipLabel,this.order,this.preview);
    this.root.append(title,intro,this.editor,this.review,this.ackLabel,this.confirm,this.status);
    page.prepend(this.root);
    this.render();void this.refresh();this.poll();
    Object.assign(window,{__g6Assignment:{inspect:()=>structuredClone({state:this.state,
      review:this.current,confirmationKey:this.confirmationKey,status:this.status.textContent})}});
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
    if(this.busy||this.confirmationKey)return;
    try{
      const state=await this.api('/state') as State;
      const signature=JSON.stringify([state.identity.streamId,
        state.drafts.map(d=>[d.draftId,d.revision,d.taskId,d.kind])]);
      if(signature===this.draftSignature)return;
      this.draftSignature=signature;
      const old=this.state;
      if(old&&old.identity.streamId!==state.identity.streamId){
        this.current=null;this.review.replaceChildren();this.selected.clear();
        this.candidates.clear();this.taskOrder=[];
      }
      this.state=state;
      const valid=new Set(state.drafts.map(d=>d.taskId));
      for(const id of [...this.selected])if(!valid.has(id))this.selected.delete(id);
      for(const id of [...this.candidates.keys()])if(!valid.has(id))this.candidates.delete(id);
      this.taskOrder=this.taskOrder.filter(id=>valid.has(id));
      for(const draft of state.drafts){
        if(!this.taskOrder.includes(draft.taskId))this.taskOrder.push(draft.taskId);
        if(!this.candidates.has(draft.taskId))
          this.candidates.set(draft.taskId,[...state.candidates[draft.kind]]);
        if(!old)this.selected.add(draft.taskId);
      }
      if(this.current&&state.drafts.some(d=>{
        const planned=this.current?.tasks.find(t=>t.taskId===d.taskId);
        return planned&&planned.revision!==d.revision;
      })){
        this.current=null;this.review.replaceChildren();this.status.textContent='草稿已修改，请重新生成联合方案。';
      }
      this.render();
    }catch{
      if(!this.confirmationKey)this.status.textContent='多任务规划暂不可用，请检查仿真是否仍在开始前。';
    }
  }

  private selections(draft:Draft){
    return this.relation.value==='sequence'?[this.state!.sequenceVehicleId]:
      this.candidates.get(draft.taskId)??[];
  }

  private render(){
    this.choices.replaceChildren();this.order.replaceChildren();
    const state=this.state;
    if(state){
      for(const draft of state.drafts){
        const card=document.createElement('fieldset');card.className='multi-task-card';
        const name=document.createElement('legend');name.textContent=`${NAMES[draft.kind]} · ${draft.taskId}`;
        card.append(name);
        const include=document.createElement('label');
        const check=document.createElement('input');check.type='checkbox';
        check.checked=this.selected.has(draft.taskId);check.disabled=this.busy||!!this.confirmationKey;
        check.onchange=()=>{
          if(check.checked)this.selected.add(draft.taskId);else this.selected.delete(draft.taskId);
          this.current=null;this.review.replaceChildren();this.render();
        };
        include.append(check,document.createTextNode('纳入本次方案'));card.append(include);
        const candidates=document.createElement('div');candidates.className='multi-candidates';
        for(const vehicle of state.candidates[draft.kind]){
          const label=document.createElement('label');
          const box=document.createElement('input');box.type='checkbox';
          box.checked=this.selections(draft).includes(vehicle);
          box.disabled=this.busy||!!this.confirmationKey||this.relation.value==='sequence';
          box.onchange=()=>{
            const current=new Set(this.candidates.get(draft.taskId)??[]);
            if(box.checked)current.add(vehicle);else current.delete(vehicle);
            this.candidates.set(draft.taskId,[...current].sort());
            this.current=null;this.review.replaceChildren();this.render();
          };
          label.append(box,document.createTextNode(`飞机 ${vehicle}`));candidates.append(label);
        }
        card.append(candidates);this.choices.append(card);
      }
      if(state.drafts.length<2){
        const hint=document.createElement('p');hint.textContent='请先保存至少两个不同类型的任务草稿。';
        this.choices.append(hint);
      }
      if(this.relation.value==='sequence'){
        const title=document.createElement('p');title.textContent='执行顺序 · 飞机 '+state.sequenceVehicleId;
        this.order.append(title);
        for(const [index,id] of this.taskOrder.entries()){
          if(!this.selected.has(id))continue;
          const line=document.createElement('div');line.className='multi-order-row';
          const text=document.createElement('span');text.textContent=`${index+1}. ${id}`;
          const up=document.createElement('button');up.textContent='上移';up.disabled=index===0||this.busy;
          up.onclick=()=>{[this.taskOrder[index-1],this.taskOrder[index]]=
            [this.taskOrder[index],this.taskOrder[index-1]];this.current=null;
            this.review.replaceChildren();this.render();};
          const down=document.createElement('button');down.textContent='下移';
          down.disabled=index===this.taskOrder.length-1||this.busy;
          down.onclick=()=>{[this.taskOrder[index+1],this.taskOrder[index]]=
            [this.taskOrder[index],this.taskOrder[index+1]];this.current=null;
            this.review.replaceChildren();this.render();};
          line.append(text,up,down);this.order.append(line);
        }
      }
    }
    const chosen=state?.drafts.filter(d=>this.selected.has(d.taskId))??[];
    this.preview.disabled=this.busy||!!this.confirmationKey||chosen.length<2||
      chosen.some(d=>this.selections(d).length===0);
    this.ackLabel.hidden=!this.current;
    this.confirm.hidden=!this.current;
    this.confirm.disabled=this.busy||!!this.confirmationKey||!this.current||
      !this.current.confirmationAllowed||!this.acknowledge.checked;
  }

  private async plan(){
    const state=this.state;if(!state||this.busy)return;
    const tasks=state.drafts.filter(d=>this.selected.has(d.taskId)).map(d=>({
      draftId:d.draftId,revision:d.revision,candidateEntityIds:this.selections(d)}));
    const taskOrder=this.taskOrder.filter(id=>this.selected.has(id));
    this.busy=true;this.status.textContent='正在计算联合方案…';this.render();
    try{
      const receipt=await this.api('/plans','POST',{
        ...state.identity,idempotencyKey:crypto.randomUUID(),tasks,taskOrder,
        relationship:this.relation.value}) as {review:Review};
      this.current=receipt.review;this.acknowledge.checked=false;
      this.showReview(receipt.review);
      this.editor.open=false;
      this.status.textContent=receipt.review.confirmationAllowed?
        '联合方案已生成，请核对后确认。':'航线超出本次仿真时长，请调整任务后重新规划。';
    }catch(error){this.current=null;this.status.textContent='联合规划失败：'+String(error);}
    finally{this.busy=false;this.render();}
  }

  private showReview(review:Review){
    const table=document.createElement('table');
    const caption=document.createElement('caption');caption.textContent='UxAS 任务分配与预计完成时间';
    const head=document.createElement('thead');
    const tr=document.createElement('tr');
    for(const text of ['任务','飞机','预计完成']){
      const th=document.createElement('th');th.textContent=text;tr.append(th);
    }
    head.append(tr);table.append(caption,head);
    const body=document.createElement('tbody');
    for(const assignment of review.plan.assignments){
      const row=document.createElement('tr');
      for(const value of [assignment.taskId,assignment.vehicleId,
        `${Math.ceil(Number(assignment.estimatedCompletionMs)/1000)} 秒`]){
        const cell=document.createElement('td');cell.textContent=value;row.append(cell);
      }
      body.append(row);
    }
    table.append(body);
    const costs=document.createElement('details');
    const title=document.createElement('summary');title.textContent='候选飞机初始转场估计';
    costs.append(title);
    for(const item of review.plan.candidateInitialCosts){
      const line=document.createElement('p');
      line.textContent=`任务 ${item.taskId} · 飞机 ${item.vehicleId} · ${Math.ceil(Number(item.initialTimeToGoMs)/1000)} 秒`;
      costs.append(line);
    }
    const routes=document.createElement('div');
    for(const command of review.plan.commands){
      const group=document.createElement('details');
      const title=document.createElement('summary');
      title.textContent=`飞机 ${command.vehicleId} · ${command.taskIds.join(' → ')} · ${command.waypoints.length} 航点 · ${(command.timeBudget.routeMeters/1000).toFixed(1)} km`;
      group.append(title);
      const budget=document.createElement('p');
      budget.textContent=`预计所需仿真时间 ${Math.ceil(command.timeBudget.requiredBudgetSeconds/60)} 分钟；可用 ${Math.floor(command.timeBudget.availableSeconds/60)} 分钟`;
      group.append(budget);
      const list=document.createElement('ol');
      for(const point of command.waypoints){
        const line=document.createElement('li');
        line.textContent=`${point.number} · ${point.longitude.toFixed(6)}, ${point.latitude.toFixed(6)} · ${point.altitudeMeters.toFixed(0)} m · ${point.taskIds.join(', ')}`;
        list.append(line);
      }
      group.append(list);routes.append(group);
    }
    this.review.replaceChildren(table,costs,routes);
  }

  private async activate(){
    const review=this.current;if(!review||this.busy||this.confirmationKey)return;
    this.busy=true;this.confirmationKey=crypto.randomUUID();
    this.status.textContent='正在确认并下发，请勿重复提交。';this.render();
    try{
      const receipt=await this.api(`/plans/${review.planId}/confirm`,'POST',{
        ...review.identity,reviewSHA256:review.reviewSHA256,
        idempotencyKey:this.confirmationKey,acknowledged:true}) as Receipt;
      this.status.textContent=receipt.status==='confirmed'?'联合方案已下发，等待任务执行。':
        `下发结果待核实：${receipt.error??receipt.status}`;
    }catch(error){this.status.textContent='下发结果待核实，请查询本次操作：'+String(error);}
    finally{this.busy=false;this.render();}
  }

  private poll(){
    if(this.stopped)return;
    if(this.confirmationKey&&!this.busy){
      void this.api(`/confirmations/${this.confirmationKey}`).then((receipt:Receipt)=>{
        const tasks=receipt.tasks?.map(t=>`${t.taskId} ${t.status}`).join(' · ');
        this.status.textContent=receipt.status==='completed'?'全部任务已完成。':
          receipt.status==='uncertain'?'下发结果待核实：'+(receipt.error??'请检查运行记录'):
          `执行中${tasks?' · '+tasks:''}`;
      }).catch(()=>{this.status.textContent='执行状态暂不可用，请检查运行记录。';});
    }else if(this.root.open&&!this.busy){void this.refresh();}
    this.timer=window.setTimeout(()=>this.poll(),2500);
  }

  destroy(){this.stopped=true;clearTimeout(this.timer);this.root.remove();
    Object.assign(window,{__g6Assignment:undefined});}
}
