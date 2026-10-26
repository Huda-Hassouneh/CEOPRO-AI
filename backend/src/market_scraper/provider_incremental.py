"""Conservative order watermarks on the existing atomic provider checkpoint authority.
Products/variants and inventory still use full snapshots: child stock changes cannot
safely be inferred from parent modified times. Failed/partial jobs never advance.
"""
from datetime import datetime,timezone,timedelta

def timestamp(value,*,provider_gmt=False):
    if not isinstance(value,str) or len(value)>50:return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:
            if not provider_gmt:return None
            parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:return None

def load_order_watermark(conn,tenant,source):
    with conn.cursor() as c:
        c.execute("SELECT continuation FROM keel_provider_sync_checkpoints WHERE tenant_id=%s AND source_id=%s AND stream_key='orders' AND configuration_version=%s",(tenant,source['source_id'],source['configuration_version']))
        row=c.fetchone()
    value=row[0].get('modified_since') if row and isinstance(row[0],dict) else None
    parsed=timestamp(value)
    return parsed.isoformat().replace('+00:00','Z') if parsed else None

def next_order_continuation(records,provider,previous=None):
    stamps=[]
    for record in records:
        if record.entity_type!='order':continue
        value=record.payload.get('updatedAt' if provider=='shopify' else 'date_modified_gmt')
        parsed=timestamp(value,provider_gmt=provider=='woocommerce')
        if parsed is None:return {'modified_since':previous} if previous else {}
        stamps.append(parsed)
    if previous:stamps.append(timestamp(previous))
    if not stamps:return {}
    return {'modified_since':max(stamps).isoformat().replace('+00:00','Z')}

def woo_modified_after(value):
    parsed=timestamp(value)
    if not parsed:raise ValueError('Invalid incremental order watermark')
    # Woo modified_after is exclusive, second precision: overlap the boundary;
    # existing provider identities/revisions deduplicate the repeated records.
    return (parsed.replace(microsecond=0)-timedelta(seconds=1)).isoformat().replace('+00:00','Z')
