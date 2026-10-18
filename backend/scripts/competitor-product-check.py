"""The custom competitor Python bridge is withdrawn; no network or DB work."""
import json
print(json.dumps({'checked': False, 'compatible': False, 'reason': 'INTEGRATION_DISABLED'}))
