"""The custom competitor Python bridge is withdrawn; no network or DB work."""
import json
print(json.dumps({'allowed': False, 'reason': 'INTEGRATION_DISABLED'}))
