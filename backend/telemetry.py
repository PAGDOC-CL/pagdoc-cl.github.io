"""Payload-free request telemetry and per-process metrics, private admin only."""
import logging
import threading
import time
from fastapi import Request
from sqlalchemy import select
import app as core
from audit_integrity import AuditSeal

log=logging.getLogger('pagdoc.http')
lock=threading.Lock()
counters={'requests':0,'server_errors':0,'duration_ms_sum':0.0,'duration_ms_max':0.0}

@core.app.middleware('http')
async def measure(request:Request,call_next):
    start=time.perf_counter();status=500
    try:
        response=await call_next(request);status=response.status_code;return response
    finally:
        elapsed=(time.perf_counter()-start)*1000
        with lock:
            counters['requests']+=1;counters['server_errors']+=int(status>=500)
            counters['duration_ms_sum']+=elapsed;counters['duration_ms_max']=max(counters['duration_ms_max'],elapsed)
        route=getattr(request.scope.get('route'),'path','unmatched')
        log.info('request method=%s route=%s status=%s duration_ms=%.2f',request.method,route,status,elapsed)

@core.app.get('/ops/metrics')
def metrics(user:core.Admin):
    with lock:result=dict(counters)
    return {'scope':'current_process','counters':result,'external_monitoring_configured':False}

@core.app.get('/ops/audit-checkpoint')
def checkpoint(user:core.Admin,db:core.Db):
    row=db.scalar(select(AuditSeal).where(AuditSeal.tenant_id==user.tenant_id).order_by(AuditSeal.audit_id.desc()).limit(1))
    return {'tenant_id':user.tenant_id,'last_audit_id':row.audit_id if row else None,'last_hash':row.event_hash if row else None,'externally_anchored':False,'note':'Export to independent controlled storage is required to anchor this checkpoint.'}
