/** A missing local API never enables cloud access. */
export function detectRuntime(staticBuild:boolean,hostname:string):'local'|'cloud'{return staticBuild||hostname.toLowerCase()==='observl.github.io'?'cloud':'local'}
export const runtimeMode=detectRuntime(import.meta.env.VITE_STATIC_DEMO==='true',window.location.hostname);
