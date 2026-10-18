import "dotenv/config";
import assert from "node:assert/strict";
import {z} from "zod";
import {prisma} from "../../src/config/database.js";
import {ensureRagSearchIndex} from "../../src/modules/rag/service/rag-search.service.js";

try {
 const [tenantId,userId]=z.tuple([z.uuid(),z.uuid()]).parse(process.argv.slice(2));
 const role=await prisma.$queryRaw<Array<{name:string;rolsuper:boolean;rolbypassrls:boolean}>>`SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user`;
 assert.equal(role[0]?.name,"ceopro_app");assert.equal(role[0]?.rolsuper,false);assert.equal(role[0]?.rolbypassrls,false);
 await prisma.$transaction(async tx=>{
  await tx.$executeRaw`SELECT set_config('app.current_tenant_id',${tenantId},true),set_config('app.current_user_id',${userId},true)`;
  const membership=await tx.tenantUser.findFirst({where:{tenantId,userId,removedAt:null,platformStatus:"active"}});
  assert(membership,"An active authorized tenant member is required");
 });
 await ensureRagSearchIndex({tenantId,userId});
 console.log("RAG indexing finished for the requested tenant. No hosted AI requests or quota charges were made.");
}catch(error){console.error(error instanceof Error?error.message:String(error));process.exitCode=1;}
finally{await prisma.$disconnect();}
