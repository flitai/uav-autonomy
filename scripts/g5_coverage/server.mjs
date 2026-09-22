// Independent read-only coverage endpoint around the qualified local map service.
import { readFileSync, writeFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { start } from '../g5_map/server.mjs';

const [configuration,output,coverageFile] = process.argv.slice(2);
const { server } = await start(JSON.parse(readFileSync(configuration,'utf8')),output);
const original = server.listeners('request');
let activeCoverageRequests=0;
server.removeAllListeners('request');
server.on('request',(request,response)=>{
  const pathname = new URL(request.url,'http://local').pathname;
  if(pathname!=='/api/coverage/v1/snapshot'){
    for(const handler of original)handler.call(server,request,response);
    return;
  }
  if(activeCoverageRequests>=16){response.writeHead(503,{'Content-Type':'application/json','Cache-Control':'no-store'}).end('{"status":"busy"}');return;}
  activeCoverageRequests++;
  let finished=false;const release=()=>{if(!finished){finished=true;activeCoverageRequests--;}};
  response.once('finish',release);response.once('close',release);
  let status=200,value;
  if(!['GET','HEAD'].includes(request.method)){status=405;value={error:'Read-only coverage service'};}
  else try{
    if(statSync(coverageFile).size>8*1024*1024)throw new Error('Coverage size limit');
    value=JSON.parse(readFileSync(coverageFile,'utf8'));
    if(value.status!=='live'||Date.now()-value.updatedAtMs>5000){status=503;value={status:'unavailable',runId:value.runId};}
  }catch{status=503;value={status:'unavailable'};}
  const body=Buffer.from(JSON.stringify(value));
  response.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Length':body.length});
  response.end(request.method==='HEAD'?undefined:body);
});
const counts=Object.create(null);
server.on('connection',socket=>socket.on('error',error=>{
  const code=['ECONNRESET','EPIPE','ETIMEDOUT'].includes(error.code)?error.code:'other';
  counts[code]=Math.min(Number.MAX_SAFE_INTEGER,(counts[code]??0)+1);socket.destroy();
}));
server.on('close',()=>writeFileSync(resolve(output,'client-errors.json'),JSON.stringify({isolated:true,counts})));
