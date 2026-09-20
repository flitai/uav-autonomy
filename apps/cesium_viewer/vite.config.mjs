import { defineConfig } from 'vite';
import { cpSync, existsSync, readFileSync } from 'node:fs';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const cesium = resolve(root, 'node_modules/cesium/Build/Cesium');
const resources = ['Workers', 'ThirdParty', 'Assets', 'Widgets'];
const mime = { '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.wasm': 'application/wasm' };
export default defineConfig({
  root,
  define: {
    CESIUM_BASE_URL: JSON.stringify('/cesium/'),
    __CESIUM_VERSION__: JSON.stringify(JSON.parse(readFileSync(resolve(root, 'node_modules/cesium/package.json'), 'utf8')).version),
  },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  build: { chunkSizeWarningLimit: 6000 },
  plugins: [{
    name: 'local-cesium-resources',
    buildStart() {
      for (const name of resources) {
        if (!existsSync(resolve(cesium, name))) throw new Error(`Missing Cesium resource: ${name}`);
      }
    },
    writeBundle(options) {
      for (const name of resources) cpSync(resolve(cesium, name), resolve(options.dir, 'cesium', name), { recursive: true });
    },
    configureServer(server) {
      server.middlewares.use('/cesium', (req, res) => {
        let path;
        try { path = resolve(cesium, '.' + decodeURIComponent(new URL(req.url, 'http://local').pathname)); }
        catch { res.statusCode = 400; res.end(); return; }
        if (!path.startsWith(cesium + sep)) { res.statusCode = 403; res.end(); return; }
        if (!existsSync(path)) { res.statusCode = 404; res.end(); return; }
        try {
          res.setHeader('Content-Type', mime[path.slice(path.lastIndexOf('.'))] || 'application/octet-stream');
          res.end(readFileSync(path));
        } catch { res.statusCode = 404; res.end(); }
      });
    },
  }],
});
