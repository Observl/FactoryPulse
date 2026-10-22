import { defineConfig,loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import {createHash} from "node:crypto";
import {readFileSync,writeFileSync,readdirSync} from "node:fs";
import {resolve,relative} from "node:path";
const version=JSON.parse(readFileSync(new URL("./package.json",import.meta.url),"utf8")).version;
export default defineConfig(({mode})=>{
 const flags=loadEnv(mode,process.cwd(),"VITE_");
 const demo=(process.env.VITE_STATIC_DEMO??flags.VITE_STATIC_DEMO)==="true";
 return {build:{rollupOptions:{output:{manualChunks(id){if(id.includes("node_modules")&&id.includes("lodash"))return "chart-utils";if(id.includes("node_modules")&&id.includes("recharts"))return "charts";if(id.includes("node_modules")&&(id.includes("d3-")||id.includes("victory-vendor")))return "chart-engine";}}}},base:demo?"/FactoryPulse/":"/",plugins:[react(),{
  name:"factorypulse-build-evidence",enforce:"post",
  writeBundle(options){
   const directory=resolve(options.dir||"dist");
   const collect=(folder:string):string[]=>readdirSync(folder,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?collect(resolve(folder,entry.name)):[resolve(folder,entry.name)]);
   const files=collect(directory).filter(file=>!file.endsWith("factorypulse-build.json")).map(file=>{const data=readFileSync(file);return {path:relative(directory,file).split("\\").join("/"),size:data.length,sha256:createHash("sha256").update(data).digest("hex")}});
   writeFileSync(resolve(directory,"factorypulse-build.json"),JSON.stringify({schema_version:1,app:"FactoryPulse",version,build_mode:demo?"static_demo":"local_service",generated_at:new Date().toISOString(),api_prefix:"/api",asset_base:demo?"/FactoryPulse/":"/",files},null,2));
  }
 }],server:{port:5173,strictPort:true,proxy:{"/api":process.env.FACTORYPULSE_API_TARGET||"http://127.0.0.1:8000"}}};
});
