import type { ReadOnlyConnection } from '../state/connection.js';
import './style.css';

type Simulation = {simulation_time_ms:string;start_time_ms:string;state:number;real_time_multiple:number};
type State = {runId:string;segmentId:string;backendRunId:string;streamId:string;durationMs:string;controlSequence:string;
  simulation:Simulation|null;ready:boolean;started:boolean};
type Operation = {key:string;sequence:string;action:string;status:string;multiple:string|null};

const text=(value:unknown)=>String(value??'');
const milliseconds=(value:string)=>`${BigInt(value)/1000n}.${(BigInt(value)%1000n).toString().padStart(3,'0')} 秒`;
const actionLabels:Record<string,string>={start:'开始',pause:'暂停',resume:'继续',rate:'倍率',reset:'重置'};
const resultLabels:Record<string,string>={pending:'正在受理',applied:'已受理，等待反馈',confirmed:'后端已确认',rejected:'后端已拒绝',uncertain:'结果待核实'};
const actionName=(value:string)=>actionLabels[value]??value;
const resultName=(value:string)=>resultLabels[value]??value;

export class ControlPanel {
  private readonly root=document.createElement('section');
  private readonly stateLabel=document.createElement('p');
  private readonly timeLabel=document.createElement('p');
  private readonly resultLabel=document.createElement('p');
  private readonly bar=document.createElement('progress');
  private readonly start=document.createElement('button');
  private readonly pause=document.createElement('button');
  private readonly resume=document.createElement('button');
  private readonly reset=document.createElement('button');
  private readonly rate=document.createElement('select');
  private readonly rateButton=document.createElement('button');
  private state:State|null=null;private operations:Operation[]=[];private timer:number|undefined;
  private polling=false;private sending=false;private stopped=false;private identity='';

  constructor(private readonly connection:ReadOnlyConnection){
    this.root.id='simulation-controls';this.root.setAttribute('aria-label','仿真控制');
    const title=document.createElement('h2');title.textContent='仿真控制';this.root.append(title);
    this.stateLabel.setAttribute('role','status');this.root.append(this.stateLabel,this.timeLabel);
    this.bar.max=1000;this.bar.hidden=true;this.bar.setAttribute('aria-label','仿真进度');this.root.append(this.bar);
    const actions=document.createElement('div');actions.className='actions';
    for(const [button,label,action] of [[this.start,'开始','start'],[this.pause,'暂停','pause'],[this.resume,'继续','resume'],[this.reset,'重置','reset']] as const){
      button.id='control-'+action;button.textContent=label;button.onclick=()=>void this.send(action);actions.append(button);
    }
    this.root.append(actions);
    const rateRow=document.createElement('div');rateRow.className='control-rate';
    const rateLabel=document.createElement('label');rateLabel.textContent='仿真倍率';rateLabel.htmlFor='control-rate';
    this.rate.id='control-rate';for(const value of ['0.25','0.5','1','2','5','10']){
      const option=document.createElement('option');option.value=value;option.textContent=value+'×';this.rate.append(option);
    }
    this.rate.value='1';this.rateButton.id='control-set-rate';this.rateButton.textContent='设置';this.rateButton.onclick=()=>void this.send('rate',this.rate.value);
    rateRow.append(rateLabel,this.rate,this.rateButton);this.root.append(rateRow);
    this.resultLabel.setAttribute('role','status');this.root.append(this.resultLabel);
    document.getElementById('backend-panel')!.insertBefore(this.root,document.getElementById('backend-panel')!.querySelector('hr'));
    this.render();void this.poll();
  }

  private async get(path:string):Promise<any>{
    const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),2500);
    try{
      const reply=await fetch('http://127.0.0.1:8001'+path,{cache:'no-store',credentials:'omit',signal:controller.signal});
      if(!reply.ok)throw Error('控制后端 HTTP '+reply.status);
      return await reply.json();
    }finally{clearTimeout(timeout);}
  }

  private async poll(){
    if(this.polling||this.stopped)return;this.polling=true;
    try{
      const state=await this.get('/api/control/v1/state') as State;
      if(!state||typeof state.runId!=='string'||typeof state.segmentId!=='string'||
         typeof state.backendRunId!=='string'||typeof state.streamId!=='string')throw Error('控制身份无效');
      const identity=state.runId+'/'+state.segmentId+'/'+state.backendRunId;
      const sameIdentity=this.identity===identity;
      if(this.identity!==identity){this.identity=identity;this.operations=[];}
      if(this.state&&sameIdentity&&BigInt(state.controlSequence)<BigInt(this.state.controlSequence))
        state.controlSequence=this.state.controlSequence;
      this.state=state;
      const list=await this.get('/api/control/v1/operations') as {runId:string;segmentId:string;items:Operation[]};
      if(list.runId!==state.runId||list.segmentId!==state.segmentId||!Array.isArray(list.items))throw Error('操作身份无效');
      this.operations=list.items;
    }catch(error){this.state=null;this.operations=[];this.stateLabel.textContent='控制后端不可用：'+text(error);}
    finally{this.polling=false;this.render();if(!this.stopped)this.timer=window.setTimeout(()=>void this.poll(),1000);}
  }

  private render(){
    const state=this.state,simulation=state?.simulation,identity=this.connection.store.identity;
    const matched=!!(state?.ready&&identity&&identity.run_id===state.backendRunId&&identity.stream_id===state.streamId&&
                    this.connection.phase==='live');
    const latest=this.operations[0],unresolved=this.operations.some(op=>op.status==='pending'||op.status==='uncertain');
    const ratePending=this.operations.some(op=>op.status==='applied'&&op.action==='rate');
    if(state)this.stateLabel.textContent=matched?'后端已同步':state.ready?'等待态势同步':
      state.started?'态势暂不可用，等待恢复':'场景已就绪，等待开始';
    this.timeLabel.textContent=simulation?'后端时间 '+milliseconds(simulation.simulation_time_ms)+
      ' · '+(['停止','运行','暂停','重置'][simulation.state]??'未知')+' · '+simulation.real_time_multiple+'×':'后端时间：等待状态';
    let progress:number|null=null;
    if(simulation&&state?.durationMs&&/^\d+$/.test(state.durationMs)&&BigInt(state.durationMs)>0n){
      const elapsed=BigInt(simulation.simulation_time_ms)-BigInt(simulation.start_time_ms);
      const total=BigInt(state.durationMs);
      progress=Number((elapsed<0n?0n:elapsed>total?total:elapsed)*1000n/total);
    }
    this.bar.hidden=progress===null;if(progress!==null)this.bar.value=progress;
    const busy=this.sending||unresolved;
    this.start.disabled=!state||state.started||state.ready||busy;
    this.pause.disabled=!matched||simulation?.state!==1||busy||ratePending;
    this.resume.disabled=!matched||simulation?.state!==2||busy;
    this.reset.disabled=!matched||busy||ratePending;
    this.rate.disabled=!matched||busy||ratePending;
    this.rateButton.disabled=this.rate.disabled;
    this.resultLabel.textContent=latest?`${actionName(latest.action)}：${resultName(latest.status)} · 操作 ${latest.sequence}`:'尚无控制操作';
  }

  private async send(action:'start'|'pause'|'resume'|'rate'|'reset',multiple?:string){
    const state=this.state;if(!state||this.sending)return;
    this.sending=true;this.render();const key=crypto.randomUUID();
    try{
      const reply=await fetch('http://127.0.0.1:8001/api/control/v1/operations',{
        method:'POST',headers:{'Content-Type':'application/json'},credentials:'omit',cache:'no-store',
        body:JSON.stringify({runId:state.runId,segmentId:state.segmentId,expectedSequence:state.controlSequence,
          idempotencyKey:key,action,multiple:multiple??null})});
      const result=await reply.json();
      if(!reply.ok&&reply.status!==202)throw Error(result.detail??'控制请求失败');
      if(this.state&&this.state.runId===state.runId&&this.state.segmentId===state.segmentId&&
         typeof result.sequence==='string')this.state.controlSequence=result.sequence;
    }catch(error){
      // The POST may have reached AMASE. Query by key before showing a failure;
      // never automatically repeat a command after a lost response.
      try{const result=await this.get('/api/control/v1/operations/'+key) as Operation;
        this.resultLabel.textContent=`${actionName(action)}：${resultName(result.status)} · 操作 ${result.sequence}`;
      }catch{this.resultLabel.textContent=`${actionName(action)}结果待核实：${text(error)}`;}
    }finally{this.sending=false;void this.poll();}
  }

  destroy(){this.stopped=true;clearTimeout(this.timer);this.root.remove();}
}
