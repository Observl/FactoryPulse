import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve, dirname} from 'node:path';
const read=path=>JSON.parse(readFileSync(path,'utf8'));
const root=read('wrangler.jsonc'), nested=read('cloudflare/wrangler.jsonc');
const normalize=(config,path)=>({...config,main:resolve(dirname(path),config.main),assets:{...config.assets,directory:resolve(dirname(path),config.assets.directory)}});
assert.deepEqual(normalize(root,'wrangler.jsonc'),normalize(nested,'cloudflare/wrangler.jsonc'),'root and explicit config must resolve to the same Worker and resources');
for(const config of [root,nested]){
 assert.ok(config.previews,'wrangler preview requires an explicit previews block');
 assert.deepEqual(config.previews.d1_databases.map(x=>x.binding).sort(),['BUSINESS_DB','DB']);
 const productionIds=new Set(config.d1_databases.map(x=>x.database_id));
 assert.ok(config.previews.d1_databases.every(x=>!productionIds.has(x.database_id)),'preview databases must be isolated from production');
 assert.equal(config.previews.vars.BUSINESS_DATABASE_ID,config.previews.d1_databases.find(x=>x.binding==='BUSINESS_DB').database_id);
 assert.deepEqual(config.previews.durable_objects,config.durable_objects);
 assert.ok(!config.previews.routes && !config.previews.triggers);
}
console.log('Cloudflare configuration checks passed: root discovery, equivalent paths, explicit preview bindings and database isolation.');
