import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const read=p=>readFile(new URL('../'+p,import.meta.url),'utf8');
const entry=await read('src/main.tsx'),auth=await read('src/Auth.tsx');
assert.match(entry,/import\("\.\/App"\)/);
assert.doesNotMatch(entry,/StaticReview|runtimeMode|CloudAuth/);
assert.doesNotMatch(auth,/CloudAuthGate|runtimeMode|VITE_STATIC_DEMO/);
for(const path of ['src/App.tsx','src/BackupPanel.tsx','src/ResourceTimeStatus.tsx'])assert.doesNotMatch(await read(path),/VITE_STATIC_DEMO/);
console.log('Unified full application entry and feature checks passed');
