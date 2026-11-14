import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const browserPage = fileURLToPath(new URL('./browser.html', import.meta.url));
const pages = new URL('../docs/', import.meta.url);
const pagesFiles = {
  '/worker.js': 'text/javascript; charset=utf-8',
  '/showcase/stand-engine-1.zip': 'application/zip',
  '/actions.html': 'text/html; charset=utf-8',
  '/github.js': 'text/javascript; charset=utf-8',
  '/studio.css': 'text/css; charset=utf-8',
};
const policy = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval' https://cdn.jsdelivr.net; worker-src 'self'; connect-src 'self' https://cdn.jsdelivr.net https://raw.githubusercontent.com; base-uri 'none'; form-action 'none'; object-src 'none'";

export default defineConfig({
  base: './',
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'brick-print-pages',
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          const path = request.url?.split('?')[0];
          if (path === '/') request.url = '/browser.html';
          const type = pagesFiles[path];
          if (!type) return next();
          readFile(new URL(path.slice(1), pages)).then(source => {
            response.setHeader('Content-Type', type);
            response.end(source);
          }).catch(next);
        });
      },
      transformIndexHtml(html, { server }) {
        if (server) return;
        return {
          html,
          tags: [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: policy }, injectTo: 'head-prepend' }],
        };
      },
    },
  ],
  build: {
    assetsDir: 'showcase',
    license: { fileName: 'showcase/third-party-licenses.md' },
    chunkSizeWarningLimit: 750,
    rolldownOptions: {
      input: browserPage,
      output: {
        codeSplitting: {
          groups: [{ name: 'three', test: /[\\/]node_modules[\\/]three[\\/]/ }],
        },
      },
    },
  },
});
