"""Request replay/recovery around the existing parser, staging and promotion.

No competing worker, extraction model, credit ledger or canonical writer.
A session advisory lock fences retries across the existing pipeline's commits.
It is explicitly released before the pooled connection is returned.
"""
from contextvars import ContextVar
from hashlib import sha256
import json,re
from fastapi import HTTPException
from src.ai import db
from src.ai.core import usage
from src.ai.extraction import ingestion_pipeline,job_management
current=ContextVar('keel_upload_request',default=None)

class UploadAttempt:
    def __init__(self,request_id,ctx):self.request_id=request_id;self.ctx=ctx;self.staging_ids=None
    def bind(self,conn,source_type,file_name,contents,rows):
        with conn.cursor() as c:
            c.execute('SELECT job_id,reservation FROM keel_file_upload_requests WHERE request_id=%s FOR UPDATE',(self.request_id,));job,reservation=c.fetchone()
            if job:
                usage._require_active(usage.get_plan(conn,self.ctx.tenant_id),usage.DOCUMENT_EXTRACTION)
                c.execute('SELECT staging_row_id FROM import_staging_rows WHERE tenant_id=%s AND job_id=%s ORDER BY staging_row_id',(self.ctx.tenant_id,str(job)));ids=[x[0] for x in c.fetchall()]
                if len(ids)!=len(rows):raise HTTPException(409,'Upload staging needs reconciliation; input row count changed.')
                c.execute("UPDATE ingestion_jobs SET rows_processed=0,rows_partial=0,rows_failed=0,job_status='PROCESSING',ended_at=NULL,error_log=NULL WHERE tenant_id=%s AND job_id=%s",(self.ctx.tenant_id,str(job)))
            else:
                reservation=usage.reserve(conn,self.ctx.tenant_id,usage.DOCUMENT_EXTRACTION,max(1,-(-len(contents)//1024)))
                source=job_management.resolve_or_create_data_source(conn,self.ctx.tenant_id,source_type,'Manual File Upload')
                job=job_management.create_ingestion_job(conn,self.ctx.tenant_id,source,file_name=file_name)
                ids=ingestion_pipeline._bulk_insert_staging_rows(conn,self.ctx.tenant_id,job,rows)
                c.execute('UPDATE keel_file_upload_requests SET job_id=%s,reservation=%s::jsonb WHERE request_id=%s',(str(job),json.dumps(reservation,default=str),self.request_id))
            c.execute("UPDATE keel_file_upload_requests SET state='processing',error_code=NULL,updated_at=now() WHERE request_id=%s",(self.request_id,))
        conn.commit();self.staging_ids=ids;return str(job),reservation

def run(file,ctx,key,callback,read,validate,detect):
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',key):raise HTTPException(422,'Invalid Idempotency-Key.')
    try:ext=detect(file.filename or '')
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    payload=read(file);validate(ext,payload);file.file.seek(0)
    if len(payload)>10485760:raise HTTPException(413,'Durable uploads support up to 10485760 bytes.')
    digest=sha256((ext+'\0'+(file.filename or '')+'\0').encode()+payload).hexdigest();lock=f'keel_upload:{ctx.tenant_id}:{key}'
    conn=db.app_role_connection(ctx.tenant_id,ctx.user_id);locked=False
    try:
        with conn.cursor() as c:
            c.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))',(lock,));locked=c.fetchone()[0]
        conn.commit()
        if not locked:raise HTTPException(409,{'code':'upload_in_progress','message':'The same upload is still processing. Retrieve its status before retrying.'})
        with conn.cursor() as c:
            c.execute('SELECT request_id,payload_hash,state,response FROM keel_file_upload_requests WHERE tenant_id=%s AND request_key=%s',(ctx.tenant_id,key));prior=c.fetchone()
            if prior:
                if prior[1]!=digest:raise HTTPException(409,'Request key is already bound to another file.')
                if prior[2]=='completed':conn.commit();return prior[3]
                request_id=str(prior[0])
            else:
                c.execute('INSERT INTO keel_file_upload_requests(tenant_id,actor_id,request_key,payload_hash,file_name,payload) VALUES(%s,%s,%s,%s,%s,%s) RETURNING request_id',(ctx.tenant_id,ctx.user_id,key,digest,file.filename or 'upload'+ext,payload));request_id=str(c.fetchone()[0])
        conn.commit();token=current.set(UploadAttempt(request_id,ctx))
        try:
            result=callback(file,ctx)
            with conn.cursor() as c:c.execute("UPDATE keel_file_upload_requests SET state='completed',response=%s::jsonb,error_code=NULL,updated_at=now() WHERE request_id=%s",(json.dumps(result,default=str),request_id))
            conn.commit();return result
        except Exception:
            conn.rollback()
            with conn.cursor() as c:c.execute("UPDATE keel_file_upload_requests SET state='failed',error_code='processing_interrupted',updated_at=now() WHERE request_id=%s",(request_id,))
            conn.commit();raise
        finally:current.reset(token)
    except Exception as exc:
        conn.rollback()
        if getattr(exc,'pgcode',None)=='23505':raise HTTPException(409,'Request key belongs to another active upload actor.') from None
        raise
    finally:
        conn.rollback()
        if locked:
            with conn.cursor() as c:c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(lock,))
            conn.commit()
        conn.close()

def status(conn,tenant_id,key):
    with conn.cursor() as c:
        c.execute('SELECT request_id,job_id,state,response,error_code,created_at,updated_at FROM keel_file_upload_requests WHERE tenant_id=%s AND request_key=%s',(tenant_id,key));row=c.fetchone()
    if not row:raise HTTPException(404,'Upload request not found.')
    return dict(zip(('request_id','job_id','state','response','error_code','created_at','updated_at'),row))
