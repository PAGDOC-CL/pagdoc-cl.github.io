"""Same-origin operational client served by the private API, without inline scripts."""
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse,FileResponse
import app as core

ROOT=Path(__file__).resolve().parent.parent
@core.app.get('/app',include_in_schema=False,response_class=HTMLResponse)
def private_app():
    source=(ROOT/'operacion.html').read_text(encoding='utf-8')
    return HTMLResponse(source.replace('data-runtime="demo"','data-runtime="private"').replace('href="assets/operations.css"','href="/app/assets/operations.css"').replace('src="assets/operations.js"','src="/app/assets/operations.js"'))

@core.app.get('/app/assets/{asset}',include_in_schema=False)
def app_asset(asset:str):
    if asset not in {'operations.js','operations.css'}:raise HTTPException(404,'Asset not found')
    return FileResponse(ROOT/'assets'/asset,media_type='text/javascript' if asset.endswith('.js') else 'text/css')
