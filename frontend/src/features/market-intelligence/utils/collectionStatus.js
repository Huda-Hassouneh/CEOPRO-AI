// Delivery to Redis is not a completed collection.
export function collectionState(event,now=Date.now()) {
  if(!event)return 'NO_REQUEST';
  if(event.status==='CANCELLED' || event.worker_status==='CANCELLED')return 'CANCELLED';
  if(event.status==='FAILED' || event.worker_status==='FAILED')return 'FAILED';
  if(event.worker_status==='COMPLETED')return event.worker_result?.rows_processed===0?'NO_RECORDS':'COMPLETED';
  if(event.worker_status==='RUNNING')return !event.worker_heartbeat_at || now-new Date(event.worker_heartbeat_at).getTime()>90000?'INTERRUPTED':'RUNNING';
  if(event.worker_error_code==='COLLECTION_RETRY_PENDING')return 'RETRYING';
  if(event.status==='PUBLISHED')return event.published_at && now-new Date(event.published_at).getTime()>300000?'UNCONFIRMED':'SUBMITTED';
  return 'QUEUED';
}
