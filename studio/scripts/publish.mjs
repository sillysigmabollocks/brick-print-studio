import { cp, rm } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const source = new URL('../dist/', import.meta.url);
const pages = new URL('../../docs/', import.meta.url);
const assets = new URL('showcase/', pages);

await rm(assets, { recursive: true, force: true });
await cp(new URL('showcase/', source), assets, { recursive: true });
// Ship the matching Python code with Pages. Catalog snapshots can refresh independently.
execFileSync('python3', ['-c', `
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
with ZipFile('docs/showcase/stand-engine-1.zip', 'w', compression=ZIP_DEFLATED) as archive:
    for path in sorted(Path('brickprint').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            archive.writestr(ZipInfo(path.as_posix()), path.read_bytes(), ZIP_DEFLATED)
`], { cwd: fileURLToPath(new URL('../../', import.meta.url)) });
await cp(new URL('browser.html', source), new URL('browser.html', pages));
