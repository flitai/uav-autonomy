// T01 candidate resource server; PMTiles/terrain and the gateway proxy belong to T03.
import { createServer } from 'node:http';
import { createReadStream, existsSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { resolve, sep, extname } from 'node:path';
const [distArgument, runArgument, portArgument = '8080'] = process.argv.slice(2);
const root = realpathSync(distArgument), run = resolve(runArgument), port = Number(portArgument);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid explicit port');
if (!existsSync(resolve(root, 'index.html'))) throw new Error('Missing candidate index.html');
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json', '.css': 'text/css; charset=utf-8', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.wasm': 'application/wasm', '.woff2': 'font/woff2' };
const server = createServer((request, response) => {
  if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405).end(); return; }
  let path;
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://local').pathname);
    path = realpathSync(resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname)));
    if (!path.startsWith(root + sep) || !statSync(path).isFile()) { response.writeHead(404).end(); return; }
  } catch { response.writeHead(404).end(); return; }
  response.writeHead(200, { 'Content-Type': types[extname(path)] || 'application/octet-stream',
    'Content-Length': statSync(path).size, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
  if (request.method === 'HEAD') response.end();
  else createReadStream(path).on('error', () => response.destroy()).pipe(response);
});
server.on('error', error => { console.error(error); process.exitCode = 1; });
let timer;
function stop() {
  clearInterval(timer);
  server.close(() => { process.exitCode = 0; });
  server.closeAllConnections();
}
server.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
  writeFileSync(resolve(run, 'ready.json'), JSON.stringify({ pid: process.pid, port, host: '127.0.0.1' }));
  timer = setInterval(() => { if (existsSync(resolve(run, 'request-stop'))) stop(); }, 100);
});
process.once('SIGINT', stop);
process.once('SIGTERM', stop);
