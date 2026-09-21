// T05 composes the qualified resource service and isolates client socket resets.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { start } from '../g5_map/server.mjs';

const [configuration, output] = process.argv.slice(2);
const counts = Object.create(null);
const { server } = await start(JSON.parse(readFileSync(configuration, 'utf8')), output);
server.on('connection', socket => {
  // HTTP keep-alive and upgraded browser sockets may reset independently of the
  // map service or backend. Every socket has an error listener until it closes.
  socket.on('error', error => {
    const code = ['ECONNRESET', 'EPIPE', 'ETIMEDOUT'].includes(error.code) ? error.code : 'other';
    counts[code] = Math.min(Number.MAX_SAFE_INTEGER, (counts[code] ?? 0) + 1);
    socket.destroy();
  });
});
server.on('close', () => writeFileSync(resolve(output, 'client-errors.json'), JSON.stringify({ isolated: true, counts })));
