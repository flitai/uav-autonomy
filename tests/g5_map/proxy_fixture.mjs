// Isolated protocol fixture: never claims to be a simulated backend.
import {createServer} from 'node:http';
import {createHash} from 'node:crypto';
import {existsSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const run=resolve(process.argv[2]),sockets=new Set();
const server=createServer((request,response)=>{
  const data=JSON.stringify({fixture:true,ready:request.url.startsWith('/api/v1/health'),entity_id:'9223372036854775807',request:request.url});
  response.writeHead(request.url.startsWith('/api/v1/snapshot')?503:200,{'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)}).end(data);
});
server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
server.on('upgrade',(request,socket)=>{
  const accept=createHash('sha1').update(request.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n');
  const body=Buffer.from(JSON.stringify({fixture:true,sequence:'9223372036854775807'}));socket.write(Buffer.concat([Buffer.from([0x81,body.length]),body]));
  setTimeout(()=>socket.end(Buffer.from([0x88,0x02,0x03,0xf5])),100);
});
server.listen({host:'127.0.0.1',port:8000,exclusive:true},()=>writeFileSync(resolve(run,'ready.json'),JSON.stringify({pid:process.pid,port:8000,fixture:true})));
const timer=setInterval(()=>{if(existsSync(resolve(run,'request-stop'))){clearInterval(timer);for(const socket of sockets)socket.destroy();server.close();}},100);
