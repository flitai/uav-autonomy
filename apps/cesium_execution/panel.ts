import './style.css';

type Inspection={selected:string|null;dirty:boolean;items:{draft:{draftId:string;revision:string;taskId:string};planId:string|null}[]};
type Review={planId:string;draftId:string;revision:string;kind:string;taskId:string;
  identity:{runId:string;segmentId:string;backendRunId:string;streamId:string};
  assignment:{vehicleId:string;order:string[]};waypoints:{number:string;longitude:number;latitude:number;altitudeMeters:number;actions:{type:string}[]}[];
  actions:{type:string}[];reviewSHA256:string;planBytesSHA256:string;confirmationAllowed:boolean;
  timeBudget:{routeMeters:number;minimumFlightSeconds:number;requiredBudgetSeconds:number;availableSeconds:number;fits:boolean}};
type Receipt={key:string;status:string;phase:string;missionCommandId?:string;taskCompleteSHA256?:string;error?:string};
const BASE='http://127.0.0.1:8004/api/tasks/v1';

export class ExecutionPanel {
  private simulationGroup=document.createElement('details');private backend:HTMLElement;
  private workspace=document.createElement('aside');private content=document.createElement('div');
  private tabs=document.createElement('nav');private taskTab=document.createElement('button');
  private reviewTab=document.createElement('button');private collapse=document.createElement('button');
  private taskPage=document.createElement('div');private reviewPage=document.createElement('div');
  private next=document.createElement('button');private activeTab:'task'|'review'='task';
  private collapsed=false;
  private root=document.createElement('section');private summary=document.createElement('div');
  private route=document.createElement('div');private message=document.createElement('p');
  private select=document.createElement('button');private confirm=document.createElement('button');
  private acknowledge=document.createElement('input');private current:Review|null=null;
  private receipt:Receipt|null=null;private key:string|null=null;private stopped=false;
  private timer:number|undefined;private busy=false;

  constructor(){
    const editor=document.getElementById('task-editor');
    const backend=document.getElementById('backend-panel');
    const stack=document.getElementById('left-stack');
    if(!editor||!backend||!stack)throw Error('任务工作区依赖的页面尚未初始化');
    this.backend=backend;
    this.simulationGroup.id='workspace-simulation';
    const simulationTitle=document.createElement('summary');simulationTitle.textContent='仿真状态与控制';
    this.simulationGroup.append(simulationTitle,backend);
    stack.insertBefore(this.simulationGroup,stack.children[1]??null);
    this.workspace.id='mission-workspace';this.workspace.setAttribute('aria-label','任务工作区');
    const header=document.createElement('header');const heading=document.createElement('h2');
    heading.textContent='任务工作区';
    this.collapse.id='workspace-collapse';this.collapse.type='button';
    this.collapse.onclick=()=>{this.collapsed=!this.collapsed;this.render();};
    header.append(heading,this.collapse);
    this.tabs.setAttribute('aria-label','任务步骤');
    this.taskTab.id='workspace-task-tab';this.taskTab.type='button';this.taskTab.textContent='1 编辑与预览';
    this.reviewTab.id='workspace-review-tab';this.reviewTab.type='button';this.reviewTab.textContent='2 审查与执行';
    this.taskTab.onclick=()=>{this.activeTab='task';this.collapsed=false;this.render();};
    this.reviewTab.onclick=()=>{this.activeTab='review';this.collapsed=false;this.render();
      if(this.selection()?.planId!==this.current?.planId)void this.load();};
    this.tabs.append(this.taskTab,this.reviewTab);
    this.taskPage.id='workspace-task-page';this.reviewPage.id='workspace-review-page';
    this.next.id='workspace-next';this.next.type='button';this.next.textContent='下一步：审查已保存的预览';
    this.next.onclick=()=>{this.activeTab='review';this.render();void this.load();};
    this.taskPage.append(editor,this.next);
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
    this.reviewPage.append(this.root);
    this.content.id='workspace-content';this.content.append(this.taskPage,this.reviewPage);
    this.workspace.append(header,this.tabs,this.content);document.body.append(this.workspace);
    this.render();this.poll();
    Object.assign(window,{__g6Execution:{inspect:()=>structuredClone({review:this.current,
      receipt:this.receipt,busy:this.busy,message:this.message.textContent,
      activeTab:this.activeTab,collapsed:this.collapsed})}});
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
      const facts=document.createElement('dl');
      for(const [name,value] of [
        ['任务',review.taskId],['草稿修订',review.revision],
        ['固定实体',review.assignment.vehicleId],
        ['执行顺序',review.assignment.order.join(' → ')],
        ['航点',String(review.waypoints.length)],
        ['航线长度',`${(review.timeBudget.routeMeters/1000).toFixed(1)} km`],
        ['最低飞行时间',`${Math.ceil(review.timeBudget.minimumFlightSeconds/60)} 分钟`],
        ['所需时间预算',`${Math.ceil(review.timeBudget.requiredBudgetSeconds/60)} 分钟`],
        ['仿真可用时间',`${Math.floor(review.timeBudget.availableSeconds/60)} 分钟`],
        ['全局动作',review.actions.map(a=>a.type).join('、')||'无']]){
        const term=document.createElement('dt');term.textContent=name;
        const description=document.createElement('dd');description.textContent=value;
        facts.append(term,description);
      }
      const details=document.createElement('details');const detailsTitle=document.createElement('summary');
      detailsTitle.textContent='方案标识与校验摘要';
      for(const [name,value] of [['方案',review.planId],['审查摘要',review.reviewSHA256],
        ['方案字节摘要',review.planBytesSHA256]]){
        const line=document.createElement('p');line.textContent=`${name}：${value}`;details.append(line);
      }
      details.prepend(detailsTitle);this.summary.replaceChildren(facts,details);
      const list=document.createElement('ol');
      for(const point of review.waypoints){const row=document.createElement('li');
        row.textContent=`航点 ${point.number}：${point.longitude.toFixed(6)}, ${point.latitude.toFixed(6)}；高程 ${point.altitudeMeters.toFixed(1)} m；动作 ${point.actions.map(a=>a.type).join('、')||'无'}`;
        list.append(row);}
      const routeTitle=document.createElement('h3');routeTitle.textContent=`完整航线 · ${review.waypoints.length} 航点`;
      this.route.replaceChildren(routeTitle,list);
      this.message.textContent=review.timeBudget.fits?'完整方案已载入，请核对后确认。':
        '航线过长，当前仿真时长不足。请缩短航线并重新预览。';
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

  private render(){
    const selection=this.selection();
    this.workspace.classList.toggle('is-collapsed',this.collapsed);
    this.collapse.textContent=this.collapsed?'展开':'收起';
    this.collapse.setAttribute('aria-expanded',String(!this.collapsed));
    this.taskTab.setAttribute('aria-current',this.activeTab==='task'?'step':'false');
    this.reviewTab.setAttribute('aria-current',this.activeTab==='review'?'step':'false');
    this.taskPage.hidden=this.activeTab!=='task';this.reviewPage.hidden=this.activeTab!=='review';
    this.next.disabled=this.busy||!!this.key||!selection;
    this.select.disabled=this.busy||!!this.key||!selection;
    this.confirm.disabled=this.busy||!!this.key||!this.current||!this.current.confirmationAllowed||!this.acknowledge.checked||
      this.selection()?.planId!==this.current.planId;}

  private poll(){if(this.stopped)return;
    if(this.key&&!this.busy){void this.api(`/confirmations/${this.key}`).then((receipt:Receipt)=>{
      this.receipt=receipt;this.message.textContent=`${receipt.status} · ${receipt.phase} · 命令 ${receipt.missionCommandId??'待核实'}${receipt.taskCompleteSHA256?' · TaskComplete 已收到':''}${receipt.error?' · '+receipt.error:''}`;
    }).catch(()=>{this.message.textContent='操作记录暂不可用，请保留本次页面并核查服务端记录。';});}
    this.render();this.timer=window.setTimeout(()=>this.poll(),1500);
  }
  destroy(){this.stopped=true;clearTimeout(this.timer);this.workspace.remove();
    document.body.append(this.backend);this.simulationGroup.remove();
    Object.assign(window,{__g6Execution:undefined});}
}
