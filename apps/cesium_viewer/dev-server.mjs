// Controlled development lifecycle for native Windows; no subprocess tree to kill.
import { createServer } from 'vite';
import { existsSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
const run = resolve(process.argv[2]);
const server = await createServer();
await server.listen();
writeFileSync(resolve(run, 'ready.json'), JSON.stringify({ pid: process.pid, port: 5173 }));
const timer = setInterval(async () => {
  if (!existsSync(resolve(run, 'request-stop'))) return;
  clearInterval(timer);
  await server.close();
}, 100);
