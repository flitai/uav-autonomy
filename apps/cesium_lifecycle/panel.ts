import './style.css';

type Identity={runId:string;segmentId:string;backendRunId:string;streamId:string};
type Operation={key:string;kind:string;status:string;planId?:string;review?:unknown;
  reason?:string;confirmationKey?:string;submittedAtMs:string};
type State={identity:Identity;status:string;
  health:{readOnly:boolean;reason:string|null};lifecycle:Operation[];
  switch:null|{status:string;phase:string;key:string}};
const API='http://127.0.0.1:8006';

export class LifecyclePanel {
  private root=document.createElement('details');
  private status=document.createElement('p');
  private rows=document.createElement('div');
  private timer:number|undefined;
  private stopped=false;
  private last:State|null=null;

  constructor(){
    const page=document.getElementById('workspace-task-page');
    if(!page)throw Error('任务工作区尚未初始化');
    this.root.id='task-lifecycle';
    const heading=document.createElement('summary');heading.textContent='操作与恢复';
    this.status.setAttribute('role','status');
    this.root.append(heading,this.status,this.rows);
    page.prepend(this.root);
    Object.assign(window,{__g6Lifecycle:{inspect:()=>structuredClone(this.last)}});
    void this.refresh();this.poll();
  }

  private async api(path:string,method='GET',body?:unknown){
    const response=await fetch(API+path,{method,cache:'no-store',credentials:'omit',
      headers:body===undefined?undefined:{'Content-Type':'application/json'},
      body:body===undefined?undefined:JSON.stringify(body)});
    const value=await response.json();
    if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:
      `HTTP ${response.status}`);
    return value;
  }

  private async restore(op:Operation){
    if(!op.planId)return;
    try{
      const review=await this.api(`/api/tasks/v3/plans/${op.planId}`);
      const bridge=(window as unknown as {__g6Replanning?:{
        restoreReview?:(review:unknown)=>Promise<void>}}).__g6Replanning;
      if(!bridge?.restoreReview)throw Error('任务审查面板不可用');
      await bridge.restoreReview(review);
      this.status.textContent='已恢复替代方案审查，请核对后确认。';
    }catch(error){this.status.textContent='方案已失效，请重新规划：'+String(error);}
  }

  private async cancel(op:Operation){
    const state=this.last;if(!state)return;
    try{
      await this.api(`/api/tasks/v4/operations/${op.key}/cancel`,'POST',{
        ...state.identity,idempotencyKey:crypto.randomUUID()});
      await this.refresh();
    }catch(error){this.status.textContent='无法取消当前方案：'+String(error);}
  }

  private async refresh(){
    if(this.stopped)return;
    try{
      const state=await this.api('/api/tasks/v4/state') as State;
      this.last=state;
      this.status.textContent=state.health.readOnly?
        '后端状态待核实，任务写入已停用。':state.switch?.status==='uncertain'?
        '切换结果待核实，请查看操作记录。':
        '当前任务操作记录可查询。';
      this.rows.replaceChildren();
      const operations=state.lifecycle.slice(-8).reverse();
      for(const op of operations){
        const row=document.createElement('div');row.className='lifecycle-row';
        const label=document.createElement('span');
        label.textContent=`${op.kind==='plan'?'替代规划':'操作'} · ${op.status} · ${op.key.slice(0,8)}`;
        row.append(label);
        if(op.status==='previewed'&&!state.health.readOnly&&!state.switch){
          const restore=document.createElement('button');restore.textContent='恢复审查';
          restore.onclick=()=>void this.restore(op);row.append(restore);
        }
        if((op.status==='previewed'||op.status==='pending')&&
            !state.health.readOnly&&!state.switch){
          const cancel=document.createElement('button');cancel.textContent='取消方案';
          cancel.onclick=()=>void this.cancel(op);row.append(cancel);
        }
        this.rows.append(row);
      }
      if(state.switch){
        const row=document.createElement('p');
        row.textContent=`切换 ${state.switch.status} · ${state.switch.phase}`;
        this.rows.append(row);
      }
      if(!operations.length&&!state.switch){
        const empty=document.createElement('p');empty.textContent='暂无任务调整操作。';
        this.rows.append(empty);
      }
    }catch{this.status.textContent='操作记录服务暂不可用。';}
  }

  private poll(){
    if(this.stopped)return;
    void this.refresh();
    this.timer=window.setTimeout(()=>this.poll(),2500);
  }

  destroy(){this.stopped=true;if(this.timer!==undefined)clearTimeout(this.timer);
    this.root.remove();delete (window as unknown as Record<string,unknown>).__g6Lifecycle;}
}
