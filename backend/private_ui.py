"""Same-origin operational client served by the private API, without inline scripts."""
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse,FileResponse
import app as core

ROOT=Path(__file__).resolve().parent.parent
@core.app.get('/app',include_in_schema=False,response_class=HTMLResponse)
def private_app():
    source=(ROOT/'operacion.html').read_text(encoding='utf-8')
    return HTMLResponse(source.replace('data-runtime="demo"','data-runtime="private"').replace('id="login-company-brand">PAG<span>DOC</span>', 'id="login-company-brand"><strong>MUFAS CHILE</strong>').replace('href="index.html"','href="/app"').replace('href="assets/operations.css"','href="/app/assets/operations.css"').replace('src="assets/operations.js"','src="/app/assets/operations.js"').replace('La demo simula estos procesos con datos ficticios.','Instancia privada. Archivos sujetos a permisos, revisión y análisis antimalware.').replace('PAGDOC: centro operativo demostrativo con servicios, planificación, revisión y pendientes ficticios.','PAGDOC: acceso privado a servicios, planificación, revisión y pendientes.'))

@core.app.get('/app/assets/{asset}',include_in_schema=False)
def app_asset(asset:str):
    tutorial_names={'overview','services','planning-write','planning-read','files-write','files-read','reviews','tasks-write','tasks-read','closeout','security','access','integrations'}
    allowed={'operations.js','operations.css','operations-film.mp4','operations-poster.jpg','tutorial-lessons.json'} | {f'tutorial-{name}.mp4' for name in tutorial_names}
    if asset not in allowed:raise HTTPException(404,'Asset not found')
    return FileResponse(ROOT/'assets'/asset,media_type={'.js':'text/javascript','.css':'text/css','.mp4':'video/mp4','.jpg':'image/jpeg','.json':'application/json'}[Path(asset).suffix])
