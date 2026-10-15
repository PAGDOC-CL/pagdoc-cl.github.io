"""Single private worker with crash recovery; document bodies stay in private tmpfs."""
import time
from pathlib import Path
from sqlalchemy import delete,text
import server
import app as core
from document_analysis import FileAnalysis,process_next


def recover_interrupted(db):
    # Call only after acquiring the exclusive worker session lock. Completed and
    # human-confirmed analyses and every original/version remain untouched.
    result=db.execute(delete(FileAnalysis).where(FileAnalysis.status=='processing'))
    db.commit()
    return result.rowcount


def main():
    heartbeat=Path('/tmp/pagdoc-analysis-heartbeat')
    with core.engine.connect() as lease:
        if lease.dialect.name=='postgresql':
            acquired=lease.execute(text('SELECT pg_try_advisory_lock(7041470016)')).scalar()
            lease.commit()
            if not acquired:raise SystemExit('PAGDOC: otro trabajador de análisis está activo.')
        with core.SessionLocal() as db:recover_interrupted(db)
        heartbeat.touch()
        while True:
            # Losing this connection loses the session lock: exit so the container
            # restarts and reacquires it before retrying interrupted work.
            try:lease.execute(text('SELECT 1'));lease.commit()
            except Exception:raise SystemExit('PAGDOC: reiniciando el trabajador para recuperar su bloqueo privado.')
            try:
                with core.SessionLocal() as db:processed=process_next(db)
                heartbeat.touch()
            except Exception:
                print('PAGDOC: análisis pendiente de revisión del servicio privado.',flush=True);processed=False
            time.sleep(1 if processed else 5)


if __name__=='__main__':main()
