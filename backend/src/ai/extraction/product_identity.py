"""Original Node reference intersection rules over the existing tenant catalog."""
import re
import unicodedata
from uuid import UUID
from fastapi import HTTPException

SKU_PATTERN=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
def normalize_sku(value):
    if value is None:return None
    if not isinstance(value,str):raise ValueError('SKU must be text.')
    value=value.strip()
    if not value:return None
    if not SKU_PATTERN.fullmatch(value):raise ValueError("SKU must contain 1–100 letters, digits, dots, underscores or hyphens, beginning with a letter or digit.")
    return value

def match_reference(reference, products):
    predicates=[]
    # Original normalizeProductReference: NFKC, trim/collapse whitespace, locale-neutral lowercase.
    norm=lambda x:re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(x)).strip()).lower()
    if reference.get('product_id'):
        try:pid=str(UUID(str(reference['product_id'])))
        except ValueError:raise HTTPException(422,'Invalid product identifier.') from None
        predicates.append(lambda p:norm(p['product_id'])==pid)
    if reference.get('sku'):predicates.append(lambda p:p.get('sku') and norm(p['sku'])==norm(reference['sku']))
    if reference.get('barcode'):predicates.append(lambda p:(p.get('metadata') or {}).get('barcode')==reference['barcode'])
    if reference.get('product_name'):
        def names(p):
            value=p.get('product_name') or {};localized=list(value.values()) if isinstance(value,dict) else [value]
            aliases=(p.get('metadata') or {}).get('import_name_aliases') or []
            return localized+([x for x in aliases if isinstance(x,str)] if isinstance(aliases,list) else [])
        predicates.append(lambda p:any(norm(v)==norm(reference['product_name']) for v in names(p)))
    if not predicates:raise HTTPException(422,'Provide a product ID, SKU, barcode or product name.')
    individual=[{p['product_id'] for p in products if pred(p)} for pred in predicates]
    matches=set.intersection(*individual)
    conflict=(any(not s for s in individual) and any(individual)) or (not matches and all(individual))
    status='conflict' if conflict else 'matched' if len(matches)==1 else 'missing' if not matches else 'ambiguous'
    return {'status':status,'product_id':next(iter(matches)) if status=='matched' else None,'candidates':sorted(matches) if status=='ambiguous' else []}

def resolve_reference(conn,tenant_id,reference):
    with conn.cursor() as c:
        c.execute('SELECT product_id,product_name,sku,metadata FROM products WHERE tenant_id=%s AND deleted_at IS NULL',(tenant_id,))
        products=[dict(zip(('product_id','product_name','sku','metadata'),(str(p),n,s,m))) for p,n,s,m in c.fetchall()]
    return match_reference(reference,products)
