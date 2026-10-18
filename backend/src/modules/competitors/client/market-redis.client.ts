import net from 'node:net';
import tls from 'node:tls';

// Narrow RESP2 transport for the existing Redis Streams contract; no model requests.
export function redisCommand(parts:string[]) {
 return Buffer.from(`*${parts.length}\r\n`+parts.map(value=>`$${Buffer.byteLength(value)}\r\n${value}\r\n`).join(''));
}
export function readRedisReply(buffer:Buffer):{value:string|null;bytes:number}|null {
 const lineEnd=buffer.indexOf('\r\n');if(lineEnd<0)return null;
 const kind=String.fromCharCode(buffer[0]!);const line=buffer.subarray(1,lineEnd).toString();
 if(kind==='-')throw new Error('REDIS_COMMAND_REJECTED');
 if(kind==='+' || kind===':')return {value:line,bytes:lineEnd+2};
 if(kind!=='$')throw new Error('REDIS_INVALID_RESPONSE');
 const size=Number(line);if(size===-1)return {value:null,bytes:lineEnd+2};
 if(!Number.isInteger(size)||size<0||size>1048576)throw new Error('REDIS_INVALID_RESPONSE');
 const end=lineEnd+2+size;if(buffer.length<end+2)return null;
 if(buffer.subarray(end,end+2).toString()!=='\r\n')throw new Error('REDIS_INVALID_RESPONSE');
 return {value:buffer.subarray(lineEnd+2,end).toString(),bytes:end+2};
}
const publishScript=`local old=redis.call('GET',KEYS[2]); if old then return old end;
 local id=redis.call('XADD',KEYS[1],'*',unpack(ARGV,2));
 redis.call('SET',KEYS[2],id,'EX',ARGV[1]); return id;`;
export async function publishMarketEvent(urlValue:string,stream:string,event:{event_id:string;tenant_id:string;source_id:string|null;competitor_id?:string|null}) {
 let url:URL;try{url=new URL(urlValue);}catch{throw new Error('REDIS_CONFIGURATION_INVALID');}
 if(!['redis:','rediss:'].includes(url.protocol))throw new Error('REDIS_CONFIGURATION_INVALID');
 const database=url.pathname.slice(1)||'0';if(!/^\d+$/.test(database))throw new Error('REDIS_CONFIGURATION_INVALID');
 const commands:string[][]=[];
 if(url.password)commands.push(url.username?['AUTH',decodeURIComponent(url.username),decodeURIComponent(url.password)]:['AUTH',decodeURIComponent(url.password)]);
 if(database!=='0')commands.push(['SELECT',database]);
 const fields=['tenant_id',event.tenant_id,'event_id',event.event_id,...(event.competitor_id?['competitor_id',event.competitor_id]:[]),...(event.source_id?['source_id',event.source_id]:[])];
 commands.push(['EVAL',publishScript,'2',stream,`ceopro:market:published:${event.event_id}`,'2592000',...fields]);
 return new Promise<string>((resolve,reject)=>{
  const host=url.hostname.replace(/^\[|\]$/g,'');const port=Number(url.port||6379);
  const socket=url.protocol==='rediss:'?tls.connect({host,port,servername:net.isIP(host)?undefined:host}):net.createConnection({host,port});
  let buffer=Buffer.alloc(0),count=0,settled=false;
  const finish=(error?:Error,value?:string)=>{if(settled)return;settled=true;clearTimeout(timer);socket.destroy();error?reject(error):resolve(value!);};
  const timer=setTimeout(()=>finish(new Error('REDIS_TIMEOUT')),8000);
  socket.once(url.protocol==='rediss:'?'secureConnect':'connect',()=>socket.write(Buffer.concat(commands.map(redisCommand))));
  socket.on('error',()=>finish(new Error('REDIS_CONNECTION_FAILED')));
  socket.on('close',()=>{if(!settled)finish(new Error('REDIS_CONNECTION_CLOSED'));});
  socket.on('data',chunk=>{
   buffer=Buffer.concat([buffer,typeof chunk==='string'?Buffer.from(chunk):chunk]);if(buffer.length>1048576){finish(new Error('REDIS_INVALID_RESPONSE'));return;}
   try{let reply;while((reply=readRedisReply(buffer))){buffer=buffer.subarray(reply.bytes);count++;
    if(count===commands.length){if(!reply.value||!/^\d+-\d+$/.test(reply.value))throw new Error('REDIS_INVALID_RESPONSE');finish(undefined,reply.value);return;}
    if(reply.value!=='OK')throw new Error('REDIS_COMMAND_REJECTED');
   }}catch{finish(new Error('REDIS_COMMAND_REJECTED'));}
  });
 });
}
