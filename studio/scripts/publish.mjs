import { cp, rm } from 'node:fs/promises';

const source = new URL('../dist/', import.meta.url);
const pages = new URL('../../docs/', import.meta.url);
const assets = new URL('showcase/', pages);

await rm(assets, { recursive: true, force: true });
await cp(new URL('showcase/', source), assets, { recursive: true });
await cp(new URL('browser.html', source), new URL('browser.html', pages));
