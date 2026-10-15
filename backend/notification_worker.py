"""Private optional daily digest worker; SMTP and each recipient must opt in."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import server
import app as core
from email_alerts import EmailPreference,dispatch_one,smtp_configured
from sqlalchemy import select


def run_once():
    if not smtp_configured():return 0
    now=datetime.now(ZoneInfo('America/Santiago'))
    if now.hour<9:return 0
    with core.SessionLocal() as db:
        ids=list(db.scalars(select(EmailPreference.user_id).where(EmailPreference.enabled==1)))
    for id in ids:
        with core.SessionLocal() as db:dispatch_one(db,id,now.date())
    return len(ids)


if __name__=='__main__':
    while True:
        try:run_once()
        except Exception:print('PAGDOC: no se completó la comprobación de avisos. Revisa el servicio privado.',flush=True)
        time.sleep(900)
