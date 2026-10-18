// Delivery acceptance is not evidence of successful discovery or collection.
export function discoveryState(event, now=Date.now()) {
  if (event.status==='CANCELLED') return 'CANCELLED';
  if (event.status==='FAILED') return 'FAILED';
  const state=event.worker_status ?? 'QUEUED';
  if (state==='FAILED') {
    if (event.worker_error_code==='HTTP_ACCESS_DENIED') return 'ACCESS_DENIED';
    if (event.worker_error_code==='ROBOTS_DISALLOWED') return 'ROBOTS_DISALLOWED';
    if (['HTTP_RATE_LIMITED','ROBOTS_UNAVAILABLE','CONTENT_UNAVAILABLE','NO_DISCOVERY_METHOD'].includes(event.worker_error_code)) return 'UNAVAILABLE';
  }
  if (state==='RUNNING' && (!event.worker_heartbeat_at || now-new Date(event.worker_heartbeat_at).getTime()>90000)) return 'INTERRUPTED';
  return state;
}
