import { createServer, request as httpRequest } from 'node:http';
import { createReadStream, existsSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { resolve, sep, extname } from 'node:path';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { tile } from './terrain.mjs';

export function parseRange(value, size, maximum) {
  const match=/^bytes=(\d*)-(\d*)$/.exec(value ?? '');
  if(!match || (!match[1] && !match[2])) throw new Error('One bounded byte range required');
  let start, end;
  if(!match[1]) {const suffix=Number(match[2]); if(suffix<=0) throw new Error('Empty suffix'); start=Math.max(0,size-suffix); end=size-1;}
  else {start=Number(match[1]); end=match[2] ? Math.min(Number(match[2]),size-1) : size-1;}
  if(![start,end].every(Number.isSafeInteger) || start<0 || start>=size || end<start || end-start+1>maximum) {
    throw new Error('Unsatisfiable or excessive byte range');
  }
  return {start,end};
}

const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8',
  '.json':'application/json','.css':'text/css; charset=utf-8','.png':'image/png','.jpg':'image/jpeg',
  '.svg':'image/svg+xml','.wasm':'application/wasm','.otf':'font/otf','.woff2':'font/woff2','.txt':'text/plain; charset=utf-8'};
const sha=data=>createHash('sha256').update(data).digest('hex');

export async function start(config, run, developmentServer) {
  const root=realpathSync(config.dist), raw=realpathSync(config.vector.path);
  const runtime=config.runtime, fieldBytes=readFileSync(config.heightfield.path);
  if(sha(fieldBytes)!==config.heightfield.sha256) throw new Error('Heightfield digest differs');
  const grid=runtime.terrain;
  if(fieldBytes.length!==grid.width*grid.height*4) throw new Error('Heightfield length differs');
  const field=new Float32Array(fieldBytes.buffer,fieldBytes.byteOffset,fieldBytes.length/4);
  if(!field.every(Number.isFinite)) throw new Error('Nonfinite heightfield');
  const rawStat=statSync(raw,{bigint:true});
  if(String(rawStat.size)!==String(config.vector.bytes) || String(rawStat.mtimeNs)!==config.vector.modifiedNs) throw new Error('Vector identity differs');
  const metrics={requests:0,ranges:0,rangeBytes:0,maxRangeBytes:0,terrainRequests:0,terrainCacheHits:0,
    terrainCacheBytes:0,peakTerrainCacheBytes:0,active:0,peakActive:0,proxyRequests:0,websockets:0,errors:0,recent:[]};
  const cache=new Map(), sockets=new Set(), upstreams=new Set();
  const etag='"'+config.vector.sha256+'"';
  let stopping=false, fatalError=false;
  const log=(path,status)=>{metrics.recent.push({path:path.slice(0,160),status});if(metrics.recent.length>128)metrics.recent.shift();};
  const json=(response,status,value)=>{const data=Buffer.from(JSON.stringify(value));response.writeHead(status,{'Content-Type':'application/json','Content-Length':data.length,'Cache-Control':'no-store'}).end(data);};
  const server=createServer((request,response)=>{
    metrics.requests++; metrics.active++; metrics.peakActive=Math.max(metrics.peakActive,metrics.active);
    let finalized=false; const finish=()=>{if(!finalized){finalized=true;metrics.active--;}};
    response.once('finish',finish);response.once('close',finish);
    response.setHeader('X-Content-Type-Options','nosniff');
    response.setHeader('Referrer-Policy','strict-origin-when-cross-origin');
    if(metrics.active>64 || stopping) {json(response,503,{error:'Resource service busy'});return;}
    let path;try{path=decodeURIComponent(new URL(request.url,'http://local').pathname);}catch{json(response,400,{error:'Invalid URL'});return;}
    if(!['GET','HEAD'].includes(request.method)){json(response,405,{error:'Read-only service'});return;}
    response.once('finish',()=>log(path,response.statusCode));
    if(path==='/api/v1/health' || path==='/api/v1/snapshot') {
      metrics.proxyRequests++;
      const upstream=httpRequest({hostname:'127.0.0.1',port:8000,path:request.url,method:request.method,
        headers:{accept:'application/json'},timeout:5000},reply=>{
        response.writeHead(reply.statusCode,{'Content-Type':reply.headers['content-type'] ?? 'application/json','Cache-Control':'no-store'});
        reply.pipe(response);reply.on('error',()=>response.destroy());
      });
      upstream.on('timeout',()=>upstream.destroy(new Error('Gateway timeout')));
      upstream.on('error',()=>{if(!response.headersSent)json(response,503,{error:'Gateway unavailable',ready:false});else response.destroy();});
      response.once('close',()=>upstream.destroy());upstream.end();return;
    }
    if(path.startsWith('/api/')){json(response,404,{error:'Unknown read-only route'});return;}
    if(path==='/map/runtime.json'){json(response,200,runtime);return;}
    if(path==='/map/health'){json(response,200,{ready:true,stage:'G5-T03',simulationConnected:false,metrics});return;}
    if(path==='/map/planet.pmtiles') {
      const current=statSync(raw,{bigint:true});
      if(current.size!==rawStat.size || current.mtimeNs!==rawStat.mtimeNs){metrics.errors++;json(response,409,{error:'Vector changed; restart qualification'});return;}
      response.setHeader('Accept-Ranges','bytes');response.setHeader('ETag',etag);
      response.setHeader('Cache-Control','private, max-age=3600');
      if(request.method==='HEAD'){response.writeHead(200,{'Content-Length':config.vector.bytes,'Content-Type':'application/vnd.pmtiles'}).end();return;}
      if(request.headers['if-range'] && request.headers['if-range']!==etag){json(response,412,{error:'Vector version differs'});return;}
      let range;try{range=parseRange(request.headers.range,config.vector.bytes,runtime.limits.rangeBytes);}catch{
        response.setHeader('Content-Range','bytes */'+config.vector.bytes);json(response,416,{error:'One range of at most '+runtime.limits.rangeBytes+' bytes required'});return;
      }
      const length=range.end-range.start+1;
      metrics.ranges++;metrics.rangeBytes+=length;metrics.maxRangeBytes=Math.max(metrics.maxRangeBytes,length);
      response.writeHead(206,{'Content-Type':'application/vnd.pmtiles','Content-Length':length,'Content-Range':`bytes ${range.start}-${range.end}/${config.vector.bytes}`});
      const stream=createReadStream(raw,range);stream.on('error',()=>{metrics.errors++;response.destroy();});
      response.once('close',()=>stream.destroy());stream.pipe(response);return;
    }
    const match=/^\/map\/terrain\/(\d+)\/(\d+)\/(\d+)\.f32$/.exec(path);
    if(match){
      metrics.terrainRequests++;let value=cache.get(path);
      if(value){metrics.terrainCacheHits++;cache.delete(path);cache.set(path,value);}
      else{
        try{value=tile(field,grid,...match.slice(1).map(Number),runtime.terrain.tileSize);}catch(error){json(response,400,{error:error.message});return;}
        while(cache.size>=runtime.limits.terrainCacheTiles){const oldest=cache.keys().next().value;metrics.terrainCacheBytes-=cache.get(oldest).data.length;cache.delete(oldest);}
        cache.set(path,value);metrics.terrainCacheBytes+=value.data.length;metrics.peakTerrainCacheBytes=Math.max(metrics.peakTerrainCacheBytes,metrics.terrainCacheBytes);
      }
      response.writeHead(200,{'Content-Type':'application/octet-stream','Content-Length':value.data.length,
        'X-Qualified-Posts':String(value.qualified),'X-Outside-Region':'reference-ellipsoid-unqualified',
        'ETag':'"'+config.heightfield.sha256+'-'+match.slice(1).join('-')+'"','Cache-Control':'private, max-age=3600'});
      response.end(request.method==='HEAD'?undefined:value.data);return;
    }
    if(path.startsWith('/map/')){json(response,404,{error:'Unknown map resource'});return;}
    if(developmentServer){developmentServer.middlewares(request,response,()=>json(response,404,{error:'Missing development resource'}));return;}
    let file;try{file=realpathSync(resolve(root,'.'+(path==='/'?'/index.html':path)));if(!file.startsWith(root+sep)||!statSync(file).isFile())throw new Error();}
    catch{json(response,404,{error:'Missing local resource'});return;}
    response.writeHead(200,{'Content-Type':types[extname(file)]??'application/octet-stream','Content-Length':statSync(file).size,
      'Cache-Control':path==='/'||path.endsWith('.html')?'no-cache':'private, max-age=3600'});
    if(request.method==='HEAD'){response.end();return;}
    const stream=createReadStream(file);stream.on('error',()=>response.destroy());response.once('close',()=>stream.destroy());stream.pipe(response);
  });
  server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
  server.on('upgrade',(request,socket,head)=>{
    if(request.url!=='/api/v1/stream' || stopping || upstreams.size>=16){socket.end('HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\n');return;}
    const upgrade=httpRequest({hostname:'127.0.0.1',port:8000,path:'/api/v1/stream',method:'GET',headers:{
      host:'127.0.0.1:8000',upgrade:'websocket',connection:'Upgrade',
      'sec-websocket-key':request.headers['sec-websocket-key'],'sec-websocket-version':'13'},timeout:5000});
    upstreams.add(upgrade); const cleanup=()=>{upgrade.destroy();upstreams.delete(upgrade);};socket.once('close',cleanup);
    upgrade.on('upgrade',(response,peer,upstreamHead)=>{
      metrics.websockets++;upstreams.add(peer);peer.setTimeout(0);
      socket.write(`HTTP/1.1 ${response.statusCode} Switching Protocols\r\n`+Object.entries(response.headers).map(([k,v])=>`${k}: ${v}\r\n`).join('')+'\r\n');
      if(upstreamHead.length)socket.write(upstreamHead);if(head.length)peer.write(head);
      peer.pipe(socket);socket.pipe(peer);
      peer.once('error',()=>socket.destroy());peer.once('close',()=>{upstreams.delete(peer);socket.destroy();});socket.once('close',()=>peer.destroy());
    });
    upgrade.on('response',response=>{socket.end(`HTTP/1.1 ${response.statusCode} Gateway unavailable\r\nConnection: close\r\n\r\n`);response.resume();});
    upgrade.on('timeout',()=>upgrade.destroy(new Error('Gateway websocket timeout')));
    upgrade.on('error',()=>{if(!socket.destroyed)socket.end('HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\n');});upgrade.end();
  });
  const port=developmentServer?5173:8080;
  await new Promise((done,reject)=>{server.once('error',reject);server.listen({host:'127.0.0.1',port,exclusive:true},done);});
  server.on('error',error=>{fatalError=true;console.error(error);stop();});
  writeFileSync(resolve(run,'ready.json'),JSON.stringify({pid:process.pid,port,host:'127.0.0.1',mode:developmentServer?'development':'production'}));
  console.log('G5_MAP_URL=http://127.0.0.1:'+port+'/');
  const timer=setInterval(()=>{if(existsSync(resolve(run,'request-stop')))stop();},100);
  async function stop(){
    if(stopping)return;stopping=true;clearInterval(timer);
    for(const upstream of upstreams)upstream.destroy();for(const socket of sockets)socket.destroy();
    await new Promise(done=>server.close(done));if(developmentServer)await developmentServer.close();
    writeFileSync(resolve(run,'server-result.json'),JSON.stringify({status:fatalError?'failed':'passed',normalExit:!fatalError,metrics},null,2));
    process.exitCode=fatalError?1:0;
  }
  process.once('SIGINT',stop);process.once('SIGTERM',stop);
  return {server,stop};
}

if(process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const [configPath,run,mode]=process.argv.slice(2), config=JSON.parse(readFileSync(configPath,'utf8'));
  let dev;
  if(mode==='development'){
    const {createServer:createVite}=await import(pathToFileURL(resolve(config.project,'node_modules/vite/dist/node/index.js')));
    dev=await createVite({configFile:resolve(config.project,'vite.config.mjs'),server:{middlewareMode:true,hmr:false},appType:'spa'});
  }
  await start(config,run,dev);
}
