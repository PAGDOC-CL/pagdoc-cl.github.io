const fs=require('node:fs'),assert=require('node:assert/strict');const {JSDOM,VirtualConsole}=require('jsdom');
const root=require('node:path').resolve(__dirname,'..')+'/';const errors=[];const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(fs.readFileSync(root+'operacion.html','utf8'),{url:'https://pagdoc-cl.github.io/operacion.html',runScripts:'dangerously',virtualConsole:vc,beforeParse(w){w.structuredClone=structuredClone;w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};}});
const w=dom.window,d=w.document,$=id=>d.getElementById(id),tick=()=>new Promise(r=>setTimeout(r,15));
function click(selector){const b=d.querySelector(selector);assert(b,selector);b.click();}
function set(name,value,event='input'){const input=$('edit-form').elements[name];assert(input,name);input.value=value;input.dispatchEvent(new w.Event(event,{bubbles:true}));}
async function submit(){ $('edit-form').dispatchEvent(new w.Event('submit',{cancelable:true,bubbles:true}));await tick();}
w.eval(fs.readFileSync(root+'assets/operations.js','utf8'));
(async()=>{
 await tick();assert.deepEqual(errors,[]);assert(!$('shell').hidden);assert($('view').textContent.includes('Una operación'));
 click('[data-view="services"]');await tick();assert($('view').textContent.includes('DEMO-014'));
 click('[data-action="new-service"]');assert($('editor').open);
 set('code','UI-TEST');set('name','Servicio ficticio de prueba');set('client','Cliente ficticio');set('location','Ubicación ficticia');set('supervisor','Supervisor ficticio');await submit();assert(!$('editor').open);assert($('view').textContent.includes('UI-TEST'));
 assert($('view').textContent.includes('Proyectos / Servicios de emergencia / Servicio programado'));
 click('[data-action="new-project"]');set('name','Proyecto de ejemplo UI');await submit();assert($('view').textContent.includes('Proyecto de ejemplo UI'));
 click('[data-action="service-section"][data-id="emergency"]');await tick();assert(!$('view').textContent.includes('UI-TEST'));
 click('[data-action="new-service"]');assert.equal($('edit-form').elements.service_kind.value,'emergency');set('code','EMERG-UI');set('name','Emergencia ficticia');set('client','Cliente ficticio');set('location','Ubicación ficticia');set('supervisor','Supervisor ficticio');await submit();assert($('view').textContent.includes('EMERG-UI'));
 click('[data-action="classify-service"][data-id="4"]');set('service_kind','scheduled','change');await submit();assert(!$('view').textContent.includes('EMERG-UI'));
 click('[data-action="service-section"][data-id="scheduled"]');await tick();assert($('view').textContent.includes('EMERG-UI'));assert(!$('view').textContent.includes('UI-TEST'));
 click('[data-action="service-section"][data-id="projects"]');await tick();
 click('[data-view="planning"]');await tick();assert.equal(d.querySelectorAll('.day').length,new Date(new Date().getFullYear(),new Date().getMonth()+1,0).getDate());
 click('[data-action="new-plan"]');set('state','rest','change');set('reason','Descanso ficticio programado');$('preview-assignment').click();await tick();assert($('form-error').textContent.includes('conflictos'));
 const replace=$('edit-form').elements.replace_existing;replace.checked=true;replace.dispatchEvent(new w.Event('input',{bubbles:true}));await submit();assert(!$('editor').open,'Plan saves after confirming preview');
 click('[data-view="reviews"]');await tick();click('[data-action="review"][data-id="3"]');set('state','observed','change');set('reason','Falta firma de revisión');await submit();assert($('view').textContent.includes('Falta firma de revisión'));
 click('[data-view="tasks"]');await tick();click('[data-action="new-task"]');set('title','Verificar equipo ficticio');await submit();assert($('view').textContent.includes('Verificar equipo ficticio'));
 click('[data-action="task-status"][data-id="3"]');set('status','done','change');await submit();assert($('view').textContent.includes('Resuelto'));
 click('[data-view="closeout"]');await tick();click('[data-action="report"][data-id="1"]');await tick();assert($('dialog-detail').textContent.includes('Cierre pendiente'));$('close-dialog').click();
 const role=$('demo-role');role.value='planner';role.dispatchEvent(new w.Event('change'));await tick();assert(d.querySelector('[data-view="reviews"]').hidden);assert(d.querySelector('[data-view="access"]').hidden);assert($('view').textContent.includes('Una operación'));
 click('[data-view="services"]');await tick();assert(d.querySelector('[data-action="new-service"]'));
 role.value='reviewer';role.dispatchEvent(new w.Event('change'));await tick();assert(!d.querySelector('[data-action="new-service"]'));assert(!d.querySelector('[data-view="reviews"]').hidden);
 click('[data-view="integrations"]');await tick();assert($('view').textContent.includes('Autorización de aplicación pendiente'));
 assert.deepEqual(errors,[]);console.log('Centro operativo: servicios, calendario, conflictos, revisión, tareas, cierre, permisos de demostración e integración pendiente: OK');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1;});
