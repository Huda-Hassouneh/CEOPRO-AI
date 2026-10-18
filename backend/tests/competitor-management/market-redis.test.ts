import assert from 'node:assert/strict';
import {test} from 'node:test';
import net from 'node:net';
import {redisCommand,readRedisReply,publishMarketEvent} from '../../src/modules/competitors/client/market-redis.client.js';
test('RESP encoder preserves Unicode byte lengths and parser handles split bulk replies without accepting malformed errors',()=>{
 const packet=redisCommand(['XADD','متجر']);assert.ok(packet.toString().includes(`$${Buffer.byteLength('متجر')}\r\nمتجر`));
 assert.equal(readRedisReply(Buffer.from('$5\r\n123')),null);
 assert.deepEqual(readRedisReply(Buffer.from('$5\r\n123-1\r\n')),{value:'123-1',bytes:11});
 assert.throws(()=>readRedisReply(Buffer.from('-NOAUTH secret\r\n')),/REDIS_COMMAND_REJECTED/);
});
test('Redis publisher authenticates/selects DB and tolerates fragmented server responses using existing stream fields',async()=>{
 let received='';const server=net.createServer(socket=>{socket.on('data',chunk=>{received+=chunk.toString();if(received.includes('tenant_id')&&received.endsWith('\r\n')){socket.write('+OK\r\n+OK\r\n$5\r\n12');setTimeout(()=>socket.end('3-1\r\n'),5);}});});
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{const address=server.address() as net.AddressInfo;
  const id=await publishMarketEvent(`redis://bridge:test-password@127.0.0.1:${address.port}/1`,'market.scrape.requested',{event_id:'event',tenant_id:'tenant',source_id:'source',competitor_id:'target-competitor'});
  assert.equal(id,'123-1');for(const value of ['AUTH','SELECT','EVAL','market.scrape.requested','ceopro:market:published:event','tenant_id','source_id','event_id','competitor_id','target-competitor'])assert.ok(received.includes(value));
  assert.ok(received.includes("redis.call('GET'"));assert.ok(received.includes("redis.call('SET'"));
 }finally{await new Promise<void>(resolve=>server.close(()=>resolve()));}
});
