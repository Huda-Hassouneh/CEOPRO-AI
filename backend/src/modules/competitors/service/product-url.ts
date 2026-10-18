import path from 'node:path';
import {isIP} from 'node:net';

/** Normalize a product URL and keep marketplace stores in their own path scope. */
export function productUrlInScope(value:string,website:string):string|null {
  try {
    const url=new URL(value),base=new URL(website);
    if(!['http:','https:'].includes(url.protocol) || url.username || url.password || url.protocol!==base.protocol || url.port!==base.port) return null;
    const host=url.hostname.toLowerCase().replace(/^www\./,'');
    if(host!==base.hostname.toLowerCase().replace(/^www\./,'') || isIP(host) || host==='localhost' || host.endsWith('.local') || host.endsWith('.localhost')) return null;
    const current=decodeURIComponent(url.pathname),root=decodeURIComponent(base.pathname);
    if(current.includes('\\') || root.includes('\\')) return null;
    const clean=path.posix.normalize(current),scope=path.posix.normalize(root).replace(/\/$/,'') || '/';
    if(scope!=='/' && clean!==scope && !clean.startsWith(scope+'/')) return null;
    url.hash='';
    return url.href;
  } catch {return null;}
}
