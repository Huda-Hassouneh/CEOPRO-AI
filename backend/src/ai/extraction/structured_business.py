"""Original strict invoice/inventory template orchestration; canonical Python writes.

No model or source-priority policy is introduced. Review changes are explicit,
version-bound, tenant-owned and committed atomically with their existing meter.
"""
import csv,io,json,re,hashlib
from itertools import islice
from src.ai.core.office_files import ensure_safe_office_archive
from datetime import date,datetime
from decimal import Decimal,ROUND_HALF_UP
from uuid import uuid4
from fastapi import HTTPException
from psycopg2.extras import Json
from openpyxl import load_workbook
from src.ai.core import usage
from src.ai.extraction import job_management,typed_imports,product_identity,ingestion_pipeline

HEADERS={'Invoices':['invoice_number','customer_name','issue_date','due_date','subtotal','tax_amount','total_amount','currency','payment_status'],'Invoice Items':['invoice_number','product_id','product_name','sku','quantity','unit_price'],'Inventory':['product_id','product_name','sku','stock_quantity','reorder_level','safety_stock','warehouse_location']}

def fail(message):raise HTTPException(422,detail=message)
def money(value):
    text=str(value).strip()
    if not re.fullmatch(r'(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,4})?',text):fail('Use a nonnegative monetary amount with at most four decimals.')
    return str(Decimal(text).quantize(Decimal('.0001')))
def quantity(value,minimum=0):
    try:v=Decimal(str(value))
    except Exception:fail('Invalid quantity.')
    if not v.is_finite() or v<minimum or v>Decimal('9999999999.9999') or v.as_tuple().exponent < -4:fail('Quantity is outside the established four-decimal range.')
    return str(v)
def iso(value,optional=False):
    if value in ('',None) and optional:return None
    try:return (value.date() if isinstance(value,datetime) else date.fromisoformat(str(value))).isoformat()
    except (TypeError,ValueError):fail('Use a valid ISO date.')
def text(value):return '' if value is None else str(value).strip()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

def parse(kind,name,payload):
    if kind not in ('invoices','inventory'):fail('Choose invoices or inventory.')
    if not payload or len(payload)>10485760:fail('Upload a nonempty file up to 10MB.')
    ext=name.lower().rsplit('.',1)[-1];sheets={}
    try:
        if ext=='csv':
            if b'\0' in payload:fail('CSV must contain UTF-8 text without NUL bytes.')
            sheets['Inventory' if kind=='inventory' else 'Invoices']=list(csv.reader(io.StringIO(payload.decode('utf-8-sig'))))
        elif ext=='xlsx' and payload.startswith(b'PK'):
            ensure_safe_office_archive(payload)
            workbook=load_workbook(io.BytesIO(payload),read_only=True,data_only=True)
            try:sheets={sheet.title:list(islice(sheet.values,1002)) for sheet in workbook}
            finally:workbook.close()
        else:fail('Use the original CSV or XLSX structured template.')
    except HTTPException:raise
    except Exception:fail('The uploaded template could not be read.')
    expected={'Inventory'} if kind=='inventory' else {'Invoices','Invoice Items'}
    if not sheets or not set(sheets)<=expected or ('Inventory' if kind=='inventory' else 'Invoices') not in sheets:fail('Use the published worksheet names.')
    parsed={'kind':kind,'invoices':[],'items':[],'inventory':[]};keys=set()
    for sheet,values in sheets.items():
        if not values:fail('Template is empty.')
        headers=[text(x) for x in values[0]]
        if len(set(headers))!=len(headers) or any(x not in HEADERS[sheet] for x in headers):fail('Template contains unknown or duplicate headers.')
        required={'Inventory':{'stock_quantity','reorder_level','safety_stock'},'Invoices':{'invoice_number','issue_date','subtotal','tax_amount','total_amount','currency','payment_status'},'Invoice Items':{'invoice_number','quantity','unit_price'}}[sheet]
        if not required<=set(headers):fail('Template is missing required columns.')
        for number,row in enumerate(values[1:],2):
            if not any(x not in ('',None) for x in row):continue
            if number>1001:fail('Structured templates support at most 1000 rows per sheet.')
            v={k:text(x) for k,x in zip(headers,row)};v.update(sheet=sheet,row=number,key=f'{sheet}:{number}')
            if sheet!='Invoices':
                if not any(v.get(x) for x in ('product_id','sku','product_name')):fail('Enter a product name, SKU or product ID.')
                if v.get('sku'):
                    try:v['sku']=product_identity.normalize_sku(v['sku'])
                    except ValueError:fail('Invalid SKU format.')
                v['productName']=v.get('product_name','');v['sku']=v.get('sku','')
            if sheet=='Inventory':
                for field in ('stock_quantity','reorder_level','safety_stock'):v[field]=quantity(v.get(field))
                key=(v.get('product_id') or v.get('sku','').casefold() or v.get('product_name','').casefold(),v.get('warehouse_location','').casefold())
                if key in keys:fail('Duplicate product/location in inventory template.')
                keys.add(key);parsed['inventory'].append(v)
            elif sheet=='Invoices':
                if not v.get('invoice_number') or len(v['invoice_number'])>100 or v['invoice_number'].casefold() in keys:fail('Invoice number is missing, too long or duplicated.')
                keys.add(v['invoice_number'].casefold());v['issue_date']=iso(v.get('issue_date'));v['due_date']=iso(v.get('due_date'),True)
                if v['due_date'] and v['due_date']<v['issue_date']:fail('Due date cannot precede issue date.')
                for field in ('subtotal','tax_amount','total_amount'):v[field]=money(v.get(field))
                if Decimal(v['subtotal'])+Decimal(v['tax_amount'])!=Decimal(v['total_amount']):fail('Total must equal subtotal plus tax.')
                v['currency']=v.get('currency','').upper();v['payment_status']=v.get('payment_status','').upper()
                if not re.fullmatch('[A-Z]{3}',v['currency']) or v['payment_status'] not in {'UNPAID','PAID','PARTIAL','OVERDUE','CANCELLED'}:fail('Invalid invoice currency or payment status.')
                if len(v.get('customer_name',''))>255:fail('Customer name is too long.')
                parsed['invoices'].append(v)
            else:
                v['quantity']=quantity(v.get('quantity'),Decimal('.0001'));v['unit_price']=money(v.get('unit_price'));v['total_price']=money((Decimal(v['quantity'])*Decimal(v['unit_price'])).quantize(Decimal('.0001'),rounding=ROUND_HALF_UP));parsed['items'].append(v)
    invoice_keys={x['invoice_number'].casefold() for x in parsed['invoices']};seen=set()
    for item in parsed['items']:
        key=(item['invoice_number'].casefold(),item.get('product_id') or item.get('sku') or item.get('product_name'))
        if key[0] not in invoice_keys or key in seen:fail('Invoice line is duplicated or has no invoice in this file.')
        seen.add(key)
    if parsed['items']:
        for invoice in parsed['invoices']:
            lines=[x for x in parsed['items'] if x['invoice_number'].casefold()==invoice['invoice_number'].casefold()]
            if not lines or sum(Decimal(x['total_price']) for x in lines)!=Decimal(invoice['subtotal']):fail('Invoice item totals must equal subtotal.')
    if not parsed['inventory'] and not parsed['invoices']:fail('Template has no data rows.')
    return parsed

def catalog(conn,tenant):
    with conn.cursor() as c:
        c.execute('SELECT product_id,product_name,sku,currency,current_price,metadata,version FROM products WHERE tenant_id=%s AND deleted_at IS NULL ORDER BY product_id',(tenant,));return [dict(zip(('product_id','product_name','sku','currency','current_price','metadata','version'),(str(a),b,s,cu,str(p),m,v))) for a,b,s,cu,p,m,v in c.fetchall()]
def load(conn,tenant,batch):
    with conn.cursor() as c:
        c.execute("SELECT source_provenance,job_id FROM keel_import_batches WHERE tenant_id=%s AND batch_id=%s",(tenant,batch));row=c.fetchone()
    if not row or not row[0].get('structured_business'):raise HTTPException(404,'Structured import not found.')
    return row[0],str(row[1])
def describe(conn,tenant,batch,choices=None):
    meta,job=load(conn,tenant,batch);parsed=meta['parsed'];products=catalog(conn,tenant);choices=choices or {};matches=[];assignments={};changes=[];issues=[];creates={}
    for row in parsed['inventory']+parsed['items']:
        match=product_identity.match_reference(row,products);pid=match['product_id'];choice=choices.get(row['key'])
        if match['status']=='conflict':issues.append({'sheet':row['sheet'],'row':row['row'],'message':'Product ID, SKU and name conflict.'})
        elif match['status']=='matched':pass
        elif choice and choice.get('action')=='select':
            pid=choice.get('productId')
            if not any(p['product_id']==pid for p in products) or (match['status']=='ambiguous' and pid not in match['candidates']):fail('Select a matching active product owned by this company.')
        elif choice and choice.get('action')=='create' and match['status']=='missing' and row.get('product_name'):
            from src.ai.routers.products import _require_catalog_admin
            _require_catalog_admin(conn,tenant,meta['actor']);sku=product_identity.normalize_sku(choice.get('sku') or row.get('sku'));currency=text(choice.get('currency')).upper()
            if row.get('sku') and sku.casefold()!=row['sku'].casefold():fail('New SKU differs from the file.')
            ident='sku:'+sku.casefold() if sku else 'name:'+row['product_name'].casefold();proposal={'name':row['product_name'],'sku':sku,'currency':currency,'price':money(choice.get('price'))}
            if ident in creates and creates[ident]!=proposal:fail('Conflicting new product definitions.')
            creates[ident]=proposal;pid='new:'+ident
        assignments[row['key']]=pid
        candidates=[p for p in products if p['product_id'] in match['candidates']]
        matches.append({'key':row['key'],'sheet':row['sheet'],'row':row['row'],'productName':row.get('product_name',''),'sku':row.get('sku',''),'status':match['status'],'productId':match['product_id'],'candidates':candidates})
        if row['sheet']=='Inventory' and pid:
            if not pid.startswith('new:'):
                with conn.cursor() as c:c.execute('SELECT stock_quantity,reorder_level,safety_stock,warehouse_location FROM inventory WHERE tenant_id=%s AND product_id=%s ORDER BY updated_at DESC LIMIT 1',(tenant,pid));prior=c.fetchone()
            else:prior=None
            changes.append({'key':row['key'],'productName':row.get('product_name') or row.get('sku'),'warehouse':row.get('warehouse_location') or None,'previous':str(prior[0]) if prior else None,'next':row['stock_quantity'],'previous_terms':[str(x) if x is not None else None for x in prior] if prior else None})
    with conn.cursor() as c:
        c.execute('SELECT primary_currency,supported_currencies FROM companies WHERE tenant_id=%s',(tenant,));primary,supported=c.fetchone()
    currencies=set([primary]+(supported or []))
    for invoice in parsed['invoices']:
        if invoice['currency'] not in currencies:issues.append({'sheet':'Invoices','row':invoice['row'],'message':'Currency is not configured for this company.'})
        with conn.cursor() as c:c.execute('SELECT 1 FROM invoices WHERE tenant_id=%s AND lower(invoice_number)=lower(%s)',(tenant,invoice['invoice_number']));exists=c.fetchone()
        if exists:issues.append({'sheet':'Invoices','row':invoice['row'],'message':'Invoice number already exists. No rows will be imported.'})
    if any(p['currency'] not in currencies for p in creates.values()):fail('New product currency is not configured for this company.')
    # The existing canonical manual inventory authority maintains one balance.
    # Different warehouses for the same resolved product cannot be collapsed by last-write wins.
    seen_inventory={}
    for row in parsed['inventory']:
        pid=assignments.get(row['key'])
        if pid and pid in seen_inventory:issues.append({'sheet':'Inventory','row':row['row'],'message':'Multiple locations resolve to one canonical product. Review source-owned stock before posting.'})
        if pid:seen_inventory[pid]=row['key']
    counts={'invoices':len(parsed['invoices']),'items':len(parsed['items']),'inventory':len(parsed['inventory']),'matched':sum(m['status']=='matched' for m in matches),'needsAttention':sum(m['status']!='matched' for m in matches),'productsToCreate':len(creates)}
    result={'draftId':str(batch),'kind':parsed['kind'],'sheets':list(dict.fromkeys(x['sheet'] for x in parsed['invoices']+parsed['items']+parsed['inventory'])),'matches':matches,'issues':issues,'counts':counts,'primaryCurrency':primary,'canCreateProducts':True,'changes':changes}
    result['reviewHash']=digest({'parsed':parsed,'choices':choices,'catalog':products,'changes':changes,'issues':issues})
    return result,assignments,creates

def preview(conn,tenant,actor,key,kind,name,payload):
    from src.ai.routers.products import _require_catalog_admin
    _require_catalog_admin(conn,tenant,actor);parsed=parse(kind,name,payload);fingerprint=hashlib.sha256(payload).hexdigest()
    with conn.cursor() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'structured:{tenant}:{key}',))
        c.execute('SELECT batch_id,source_provenance FROM keel_import_batches WHERE tenant_id=%s AND idempotency_key=%s',(tenant,'structured:'+key));prior=c.fetchone()
    if prior:
        if prior[1]['file_hash']!=fingerprint or prior[1]['actor']!=actor:raise HTTPException(409,'Preview request identity changed.')
        return describe(conn,tenant,prior[0])[0]
    source=job_management.resolve_or_create_data_source(conn,tenant,'XLSX_UPLOAD' if name.lower().endswith('.xlsx') else 'CSV_UPLOAD','Manual File Upload');job=job_management.create_ingestion_job(conn,tenant,source,file_name=name)
    # The existing immutable typed authority holds the full parsed source as provenance.
    rows=[]
    for i,row in enumerate(parsed['inventory']+parsed['items']):
        values={'product_id':row.get('product_id'),'sku':row.get('sku'),'product_name':row.get('product_name'),'quantity':row.get('stock_quantity',row.get('quantity')),'quantity_semantics':'stock_quantity'} if kind=='inventory' else {'invoice_id':row['invoice_number'],'invoice_date':next(x['issue_date'] for x in parsed['invoices'] if x['invoice_number'].casefold()==row['invoice_number'].casefold()),'currency':next(x['currency'] for x in parsed['invoices'] if x['invoice_number'].casefold()==row['invoice_number'].casefold()),'product_id':row.get('product_id'),'sku':row.get('sku'),'product_name':row.get('product_name'),'quantity':row['quantity'],'unit_price':row['unit_price']}
        rows.append({'source_row_key':row['key'],'row_number':i,'typed_values':{k:v for k,v in values.items() if v not in (None,'')}})
    meta={'structured_business':True,'parsed':parsed,'file_hash':fingerprint,'file_bytes':len(payload),'actor':actor}
    batch=typed_imports.persist_import_draft(conn,tenant_id=tenant,actor_id=actor,source_id=source,job_id=job,category='inventory' if kind=='inventory' else 'invoice',rows=rows,idempotency_key='structured:'+key,provenance=meta)
    return describe(conn,tenant,batch['batch_id'])[0]

def confirm(conn,tenant,actor,batch,choices,review_hash):
    from src.ai.routers.products import _require_catalog_admin,create_product,upsert_inventory
    _require_catalog_admin(conn,tenant,actor)
    with conn.cursor() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('structured-post:'+tenant,))
        c.execute('SELECT response,request_hash FROM keel_structured_import_posts WHERE tenant_id=%s AND batch_id=%s',(tenant,batch));prior=c.fetchone()
    request_hash=digest({'choices':choices,'reviewHash':review_hash})
    meta,job=load(conn,tenant,batch)
    if meta['actor']!=actor:raise HTTPException(403,'Only the original authorized reviewer can confirm this preview.')
    if prior:
        if prior[1]!=request_hash:raise HTTPException(409,'A different confirmation already committed this draft.')
        return prior[0]
    meta,job=load(conn,tenant,batch)
    if meta['actor']!=actor:raise HTTPException(403,'Only the original authorized reviewer can confirm this preview.')
    with conn.cursor() as c:
        c.execute('SELECT product_id FROM products WHERE tenant_id=%s AND deleted_at IS NULL FOR UPDATE',(tenant,));c.fetchall()
        c.execute('SELECT inventory_id FROM inventory WHERE tenant_id=%s FOR UPDATE',(tenant,));c.fetchall()
    review,assignments,creates=describe(conn,tenant,batch,choices)
    if review['reviewHash']!=review_hash:raise HTTPException(409,'Products, stock or review changed. Review again.')
    if review['issues'] or any(p is None for p in assignments.values()):raise HTTPException(409,'Resolve all import findings before confirmation.')
    usage.reserve(conn,tenant,usage.DOCUMENT_EXTRACTION,max(1,-(-meta['file_bytes']//1024)))
    proposed={}
    for ident,p in creates.items():
        usage.ensure_capacity(conn,tenant,usage.TRACKED_PRODUCTS,1)
        item=create_product(conn,tenant,actor,{'en':p['name']},None,None,None,Decimal(p['price']),None,p['currency'],sku=p['sku']);proposed['new:'+ident]=item['product_id']
    assignments={k:proposed.get(v,v) for k,v in assignments.items()};parsed=meta['parsed'];ids=[];transaction_ids=[];stock=[]
    with conn.cursor() as c:
        for invoice in parsed['invoices']:
            iid=str(uuid4());ids.append(iid)
            c.execute('INSERT INTO invoices(invoice_id,tenant_id,invoice_number,customer_name,issue_date,due_date,subtotal,tax_amount,total_amount,currency,payment_status,created_by_user_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(iid,tenant,invoice['invoice_number'],invoice.get('customer_name') or None,invoice['issue_date'],invoice['due_date'],invoice['subtotal'],invoice['tax_amount'],invoice['total_amount'],invoice['currency'],invoice['payment_status'],actor))
            for row in [x for x in parsed['items'] if x['invoice_number'].casefold()==invoice['invoice_number'].casefold()]:
                pid=assignments[row['key']];c.execute('INSERT INTO invoice_items(tenant_id,invoice_id,product_id,quantity,unit_price,total_price) VALUES(%s,%s,%s,%s,%s,%s)',(tenant,iid,pid,row['quantity'],row['unit_price'],row['total_price']))
                if invoice['payment_status']=='PAID':
                    c.execute("INSERT INTO transactions(tenant_id,product_id,quantity_sold,unit_price,total_price,original_currency,sale_source,transaction_date) VALUES(%s,%s,%s,%s,%s,%s,'POS',%s) RETURNING transaction_id",(tenant,pid,row['quantity'],row['unit_price'],row['total_price'],invoice['currency'],invoice['issue_date']));transaction_ids.append(str(c.fetchone()[0]))
        for row in parsed['inventory']:
            pid=assignments[row['key']];change=next(x for x in review['changes'] if x['key']==row['key']);updated=upsert_inventory(conn,tenant,pid,Decimal(row['stock_quantity']),Decimal(row['reorder_level']),Decimal(row['safety_stock']))
            c.execute('UPDATE inventory SET warehouse_location=%s WHERE tenant_id=%s AND product_id=%s',(row.get('warehouse_location') or None,tenant,pid))
            stock.append({'product_id':pid,'previous':change['previous'],'next':row['stock_quantity'],'warehouse':row.get('warehouse_location')})
        result={'kind':parsed['kind'],'imported':len(ids) if parsed['kind']=='invoices' else sum(x['previous'] is None for x in stock),'updated':sum(x['previous'] is not None for x in stock),'invoiceItems':len(parsed['items']),'productsCreated':len(proposed),'job_id':job,'canonical_write_performed':True}
        evidence={'invoice_ids':ids,'transaction_ids':transaction_ids,'stock_changes':stock,'review_hash':review_hash}
        c.execute('INSERT INTO keel_structured_import_posts(tenant_id,batch_id,actor_id,request_hash,response,evidence) VALUES(%s,%s,%s,%s,%s,%s)',(tenant,batch,actor,request_hash,Json(result),Json(evidence)))
        c.execute("INSERT INTO audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json) VALUES(%s,%s,'STRUCTURED_IMPORT_POSTED','keel_import_batches',%s,%s)",(tenant,actor,batch,Json(evidence)))
        job_management.finalize_ingestion_job(conn,tenant,job,'COMPLETED')
    return result
