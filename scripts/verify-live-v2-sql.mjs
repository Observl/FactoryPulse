// Exercise the deployed SQL report implementation against the actual cloud D1.
// This validates SQL and response contracts, not browser authentication.
import {readFile,writeFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {sqlRead} from '../cloudflare/identity/sql-analysis.mjs';
const file=resolve('.secrets/business.json'),config=JSON.parse(await readFile(file,'utf8'));
const token=(await readFile(resolve(dirname(file),config.token_file),'utf8')).trim();
const url=`https://api.cloudflare.com/client/v4/accounts/${config.account_id}/d1/database/${config.database_id}/query`;
const checks=[];
let totalReads=0;
const db={prepare(sql){return {params:[],bind(...params){this.params=params;return this},async all(){
 const response=await fetch(url,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({sql,params:this.params})});
 const body=await response.json();
 if(!body.success||!body.result?.[0]?.success)throw new Error(JSON.stringify(body.errors));
 totalReads+=body.result[0].meta?.rows_read||0;
 return body.result[0];
 },async first(){return (await this.all()).results[0]||null}}}};
for(const path of ['/api/overview','/api/data/summary','/api/data-quality','/api/resources/inventory','/api/analysis/equipment?limit=1','/api/analysis/work-orders?limit=1']){
 const started=Date.now(),before=totalReads;
 const r=await sqlRead(new Request('https://live-sql-check'+path),{BUSINESS_DB:db,BUSINESS_SCHEMA_VERSION:'2',BUSINESS_DATABASE_ID:config.database_id},{role:'developer',staff_id:0});
 const v=await r.json();
 const check={scope:'direct_cloud_d1_sql',path,status:r.status,elapsed_ms:Date.now()-started,rows_read:totalReads-before,schema_version:v.schema_version,
  device_count:v.device_count??v.metrics?.total,reading_count:v.reading_count,computed_by:v.computed_by};
 if(v.detail)check.detail=v.detail;
 checks.push(check);console.log(JSON.stringify(check));
 if(r.status!==200)throw new Error('SQL report failed');
}
await writeFile('outputs/database-v2/live-sql-verification.json',JSON.stringify(checks,null,2));
