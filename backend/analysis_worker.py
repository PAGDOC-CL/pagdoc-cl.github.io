"""Private offline analysis worker. Plaintext exists only in private temporary files."""
import time
from pathlib import Path
import server
import app as core
from document_analysis import process_next

if __name__=='__main__':
    while True:
        try:
            with core.SessionLocal() as db:processed=process_next(db)
            Path('/tmp/pagdoc-analysis-heartbeat').touch()
        except Exception:
            print('PAGDOC: análisis pendiente de revisión del servicio privado.',flush=True);processed=False
        time.sleep(1 if processed else 5)
