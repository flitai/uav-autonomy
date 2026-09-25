import './style.css';

type Inspection={selected:string|null;dirty:boolean;items:{draft:{draftId:string;revision:string;taskId:string};planId:string|null}[]};
type Review={planId:string;draftId:string;revision:string;kind:string;taskId:string;
  identity:{runId:string;segmentId:string;backendRunId:string;streamId:string};
  assignment:{vehicleId:string;order:string[]};waypoints:{number:string;longitude:number;latitude:number;altitudeMeters:number;actions:{type:string}[]}[];
  actions:{type:string}[];reviewSHA256:string;planBytesSHA256:string};
type Receipt={key:string;status:string;phase:string;missionCommandId?:string;taskCompleteSHA256?:string;error?:string};
const BASE='http://127.0.0.1:8004/api/tasks/v1';

export class ExecutionPanel {
  private root=document.createElement('section');private summary=document.createElement('div');
  private route=document.createElement('div');private message=document.createElement('p');
  private select=document.createElement('button');private confirm=document.createElement('button');
  private acknowledge=document.createElement('input');private current:Review|null=null;
  private receipt:Receipt|null=null;private key:string|null=null;private stopped=false;
  private timer:number|undefined;private busy=false;

  constructor(){
    this.root.id='execution-review';this.root.setAttribute('aria-label','方案审查与确认下发');
    const title=document.createElement('h2');title.textContent='方案审查与确认下发';
    const hint=document.createElement('p');hint.textContent='先审查完整航线和固定分配，再明确确认。确认会启动仿真并下发该方案。';
    this.select.id='execution-load';this.select.textContent='审查当前预览';this.select.onclick=()=>void this.load();
    this.acknowledge.id='execution-ack';this.acknowledge.type='checkbox';
    this.acknowledge.onchange=()=>this.render();
    const label=document.createElement('label');label.htmlFor=this.acknowledge.id;
    label.append(this.acknowledge,document.createTextNode('我已核对分配、顺序与完整航线'));
    this.confirm.id='execution-confirm';this.confirm.textContent='确认下发此方案';
    this.confirm.onclick=()=>void this.submit();
    this.message.id='execution-status';this.message.setAttribute('role','status');
    this.summary.id='execution-summary';this.route.id='execution-route';
    this.root.append(title,hint,this.select,this.summary,this.route,label,this.confirm,this.message);
    document.body.append(this.root);this.render();this.poll();
    Object.assign(window,{__g6Execution:{inspect:()=>structuredClone({review:this.current,
      receipt:this.receipt,busy:this.busy,message:this.message.textContent})}});
  }

  private selection(){
    const handle=(window as Window & {__g6Tasks?:{inspect:()=>Inspection}}).__g6Tasks;
    const state=handle?.inspect();
    const item=state?.items.find(row=>row.draft.draftId===state.selected);
    return state&&!state.dirty&&item?.planId?item:null;
  }

  private async api(path:string,method='GET',body?:unknown){
    const reply=await fetch(BASE+path,{method,cache:'no-store',credentials:'omit',
      headers:body===undefined?undefined:{'Content-Type':'application/json'},
      body:body===undefined?undefined:JSON.stringify(body)});
    const result=await reply.json();
    if(!reply.ok)throw Error(typeof result.detail==='string'?result.detail:`HTTP ${reply.status}`);
    return result;
  }

  private async load(){
    const item=this.selection();if(!item)return;
    this.busy=true;this.render();
    try{
      const review=await this.api(`/plans/${item.planId}/review`) as Review;
      if(this.selection()?.planId!==review.planId)throw Error('当前草稿或预览已改变，请重新审查');
      this.current=review;this.acknowledge.checked=false;this.key=null;this.receipt=null;
      this.summary.textContent=`方案 ${review.planId} · 任务 ${review.taskId} · 修订 ${review.revision} · 固定实体 ${review.assignment.vehicleId} · 顺序 ${review.assignment.order.join(' → ')} · ${review.waypoints.length} 航点 · 全局动作 ${review.actions.map(a=>a.type).join('、')||'无'} · 审查摘要 ${review.reviewSHA256} · 方案字节摘要 ${review.planBytesSHA256}`;
      const list=document.createElement('ol');
      for(const point of review.waypoints){const row=document.createElement('li');
        row.textContent=`航点 ${point.number}：${point.longitude.toFixed(6)}, ${point.latitude.toFixed(6)}；高程 ${point.altitudeMeters.toFixed(1)} m；动作 ${point.actions.map(a=>a.type).join('、')||'无'}`;
        list.append(row);}
      this.route.replaceChildren(list);
      this.message.textContent='完整方案已载入，请核对后确认。';
    }catch(error){this.current=null;this.message.textContent='审查失败：'+String(error);}
    finally{this.busy=false;this.render();}
  }

  private async submit(){
    const review=this.current;if(!review||!this.acknowledge.checked||this.busy||this.key)return;
    this.busy=true;this.key=crypto.randomUUID();this.message.textContent='确认处理中，请勿重复提交。';this.render();
    try{
      this.receipt=await this.api(`/plans/${review.planId}/confirm`,'POST',{
        ...review.identity,draftId:review.draftId,expectedRevision:review.revision,
        reviewSHA256:review.reviewSHA256,idempotencyKey:this.key,acknowledged:true}) as Receipt;
      this.message.textContent=`${this.receipt.status} · ${this.receipt.phase} · 命令 ${this.receipt.missionCommandId??'待核实'}`;
    }catch(error){this.message.textContent='确认结果未知，请查询操作记录：'+String(error);}
    finally{this.busy=false;this.render();}
  }

  private render(){this.select.disabled=this.busy||!!this.key||!this.selection();
    this.confirm.disabled=this.busy||!!this.key||!this.current||!this.acknowledge.checked||
      this.selection()?.planId!==this.current.planId;}

  private poll(){if(this.stopped)return;
    if(this.key&&!this.busy){void this.api(`/confirmations/${this.key}`).then((receipt:Receipt)=>{
      this.receipt=receipt;this.message.textContent=`${receipt.status} · ${receipt.phase} · 命令 ${receipt.missionCommandId??'待核实'}${receipt.taskCompleteSHA256?' · TaskComplete 已收到':''}${receipt.error?' · '+receipt.error:''}`;
    }).catch(()=>{this.message.textContent='操作记录暂不可用，请保留本次页面并核查服务端记录。';});}
    this.render();this.timer=window.setTimeout(()=>this.poll(),1500);
  }
  destroy(){this.stopped=true;clearTimeout(this.timer);this.root.remove();
    Object.assign(window,{__g6Execution:undefined});}
}
