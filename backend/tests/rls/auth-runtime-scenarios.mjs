import assert from 'node:assert/strict';
import { randomUUID, randomBytes } from 'node:crypto';
import express from 'express';
import { PGLiteSocketServer } from '@electric-sql/pglite-socket';

// Actual Prisma queries and auth logic against disposable PostgreSQL, including
// HTTP login/session/logout. Only email transport is captured via register's
// existing injected sender; no DB, password, permission, or JWT logic is mocked.
export async function runAuthRuntimeScenarios(db) {
  const previous = { DATABASE_URL:process.env.DATABASE_URL, JWT_SECRET:process.env.JWT_SECRET };
  let socket, http, prisma;
  try {
    await db.exec(`SELECT set_config('app.auth_email','',false),set_config('app.current_user_id','',false),set_config('app.current_tenant_id','',false);
      SET SESSION AUTHORIZATION ceopro_app;`);
    socket = new PGLiteSocketServer({db,host:'127.0.0.1',port:0});
    await socket.start();
    const url = new URL(`postgresql://${socket.getServerConn()}/postgres`);
    url.username='ceopro_app';
    process.env.DATABASE_URL=url.toString();
    process.env.JWT_SECRET=randomBytes(32).toString('hex');
    ({prisma}=await import('../../src/config/database.ts'));
    const auth=await import('../../src/modules/auth/service/auth.service.ts');
    const repo=await import('../../src/modules/auth/repo/auth.repo.ts');
    const {default:authRouter}=await import('../../src/modules/auth/route/auth.route.ts');
    const identity=(await prisma.$queryRawUnsafe('SELECT current_user AS name,session_user AS session_user'))[0];
    assert.equal(identity.name,'ceopro_app');assert.equal(identity.session_user,'ceopro_app');
    await assert.rejects(()=>db.query('SET ROLE ceopro_platform_overview_reader'),error=>error.code==='42501');
    console.log('PASS real Prisma runtime current_user/session_user=ceopro_app');
    const email=`${randomUUID()}@rls-runtime.example`;
    const password='RlsRegressionPass123!';
    let delivered;
    const registered=await auth.register({email,password,fullName:'RLS test',businessName:'RLS runtime',businessType:'retail',countryCode:'JO',primaryCurrency:'USD',preferredLanguage:'en'},async payload=>{delivered=payload;});
    assert.equal(registered.success,true);assert.equal(registered.data.verificationRequired,true);assert(delivered?.token);
    assert.equal(await repo.findUserByEmail(email),null);
    const confirmed=await auth.confirmEmail(delivered.token);assert.equal(confirmed.success,true);
    const exchange=await auth.exchangeVerificationCode(confirmed.data.code);assert.equal(exchange.success,true);
    assert.equal(exchange.data.session.refreshToken,null);
    const duplicate=await auth.register({email,password,businessName:'RLS duplicate',countryCode:'JO',primaryCurrency:'USD'},async()=>assert.fail('Existing email must not send a new signup email'));
    assert.equal(duplicate.success,true);
    console.log('PASS real registration, confirmation, one-time exchange and existing-email signup');
    const app=express();app.use(express.json());app.use('/auth',authRouter);
    app.use((error,_req,res,_next)=>res.status(500).json({error:{message:error.message}}));
    http=await new Promise(resolve=>{const server=app.listen(0,'127.0.0.1',()=>resolve(server));});
    const base=`http://127.0.0.1:${http.address().port}`;
    const login=await fetch(`${base}/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
    const body=await login.json();assert.equal(login.status,200,JSON.stringify(body));assert(body.session.accessToken);
    assert.equal(body.session.refreshToken,null);
    const authorization=`Bearer ${body.session.accessToken}`;
    const session=await fetch(`${base}/auth/session`,{headers:{authorization}});assert.equal(session.status,200,await session.text());
    const logout=await fetch(`${base}/auth/logout`,{method:'POST',headers:{authorization}});assert.equal(logout.status,200);assert.equal((await logout.json()).loggedOut,true);
    const revoked=await fetch(`${base}/auth/session`,{headers:{authorization}});assert.equal(revoked.status,401);
    const invalid=await fetch(`${base}/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password:'incorrect'})});assert.equal(invalid.status,401);
    console.log('PASS real HTTP login, session revalidation, logout, revoked-session and bad-password rejection');
    console.log('NOTE refresh-token endpoint is not implemented in the current Node API; refreshToken remains null');
  } finally {
    if(http) await new Promise(resolve=>http.close(resolve));
    if(prisma) await prisma.$disconnect();
    if(socket) await socket.stop();
    for(const [key,value] of Object.entries(previous)) {if(value===undefined)delete process.env[key];else process.env[key]=value;}
  }
}
