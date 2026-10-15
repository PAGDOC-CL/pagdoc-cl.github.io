const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'..'),errors=[],calls=[],downloads=[];
const docs=[],vehicles=[{id:1,label:'Fictitious truck',plate:'TEST11'}];
let onboardingSeen=false;
let signedIn=false,rejectUpload=false,logoVersion=0,rejectName='';const previewHashes=new Map();
const me={id:1,email:'admin@example.invalid',role:'admin',capabilities:['plan.read','plan.write','documents.read','documents.write','documents.review','tasks.read','tasks.write','users.manage']};
let emailPref={enabled:false,days_before:30,include_expiring:true,include_expired:true,include_overdue:true};
const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(fs.readFileSync(path.join(root,'operacion.html'),'utf8').replace('data-runtime="demo"','data-runtime="private"'),{
 url:'https://localhost:8443/app',runScripts:'dangerously',virtualConsole:vc,beforeParse(w){
  w.structuredClone=structuredClone;Object.defineProperty(w.crypto,'subtle',{value:require('node:crypto').webcrypto.subtle});
    w.HTMLMediaElement.prototype.play=async function(){Object.defineProperty(this,'paused',{value:false,configurable:true});};w.HTMLMediaElement.prototype.pause=function(){Object.defineProperty(this,'paused',{value:true,configurable:true});};w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.URL.createObjectURL=()=> 'blob:fictitious-private-download';w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){downloads.push(this.download);};
  w.fetch=async(route,options)=>{
   calls.push({route,options});const url=new URL(route,'https://localhost:8443');let status=200,body;
   const payload=typeof options.body==='string'?JSON.parse(options.body):null;
   if(url.pathname==='/app/assets/tutorial-lessons.json')body=JSON.parse(fs.readFileSync(path.join(root,'assets/tutorial-lessons.json'),'utf8'));
   else if(url.pathname==='/login/branding')body={logo_version:logoVersion,name:logoVersion?'Fictitious Company':undefined};
   else if(url.pathname==='/auth/login'){signedIn=true;w.document.cookie='pagdoc_csrf=fictitious-csrf; Path=/; Secure; SameSite=Strict';body={authenticated:true};}
   else if(!signedIn){status=401;body={detail:'Authentication required'};}
   else if(url.pathname==='/ops/onboarding/start'){assert.equal(options.method,'POST');assert.equal(options.headers['X-PAGDOC-CSRF'],'fictitious-csrf');body={show_tutorial:!onboardingSeen&&!payload.legacy_seen};onboardingSeen=true;}
   else if(url.pathname==='/ops/email-alerts'){if(options.method==='PUT')Object.assign(emailPref,payload);body={...emailPref,recipient:me.email,delivery_configured:false};}
   else if(url.pathname==='/ops/email-alerts/preview')body={recipient:me.email,expiring:2,expired:1,overdue_tasks:3,missing_dates:4,delivery_configured:false};
   else if(url.pathname==='/ops/branding')body={logo_version:logoVersion};
   else if(url.pathname==='/ops/branding/logo'){assert(options.body instanceof w.File);assert.equal(options.headers['Content-Type'],'image/png');assert.equal(options.headers['X-PAGDOC-CSRF'],'fictitious-csrf');body={logo_version:++logoVersion};}
   else if(url.pathname==='/ops/bootstrap')body={me,tenant:{id:1,name:'Fictitious Company'},workers:[],projects:[],users:[]};
   else if(url.pathname==='/ops/dashboard')body={active_services:0,pending_tasks:0,overdue_tasks:0,tomorrow_assignments:0,tomorrow_blocked:0};
   else if(url.pathname==='/ops/integrations')body={storage:{binary_http_enabled:true}};
   else if(url.pathname==='/ops/files/status')body={enabled:true,ready_for_upload:true,max_bytes:15*1024*1024};
   else if(url.pathname==='/ops/files/subjects')body={company:'Fictitious Company',vehicles};
   else if(url.pathname==='/ops/files/batch/preview'){
    body={items:payload.entries.map(entry=>{const key=entry.subject_kind+':'+entry.vehicle_id+':'+entry.path;previewHashes.set(key,entry.sha256);const doc=docs.find(doc=>doc.title===entry.path&&doc.subject_kind===entry.subject_kind&&doc.vehicle_id===entry.vehicle_id);return {...entry,subject_name:'Fictitious subject',document_id:doc?.id||null,expected_version:doc?.version||0,status:doc?(doc.sha256===entry.sha256?'identical':doc.version?'replace':'resume'):'new'};})};
   }else if(url.pathname==='/ops/files/batch/item'){
    assert(options.body instanceof w.File);assert.equal(options.headers['X-PAGDOC-CSRF'],'fictitious-csrf');
    const path=url.searchParams.get('path'),kind=url.searchParams.get('subject_kind'),vehicle=kind==='vehicle'?+url.searchParams.get('vehicle_id'):null;
    let doc=docs.find(doc=>doc.title===path&&doc.subject_kind===kind&&doc.vehicle_id===vehicle);
    if(path.split('/').at(-1)===rejectName){status=422;body={detail:'Fictitious antivirus rejection'};}
    else{if(!doc){doc={id:docs.length+1,title:path,subject_kind:kind,vehicle_id:vehicle,subject_name:'Fictitious subject',version:0,expires_on:null,review_state:'pending',expiry_status:'no_date'};docs.push(doc);}assert.equal(+url.searchParams.get('expected_version'),doc.version);if(doc.version)assert.equal(url.searchParams.get('allow_replace'),'true');doc.version++;doc.file_name=path.split('/').at(-1);doc.sha256=previewHashes.get(kind+':'+vehicle+':'+path);body={document_id:doc.id,version:doc.version,status:doc.version>1?'replaced':'created'};}
   }
   else if(url.pathname==='/ops/files/documents'&&options.method==='POST'){
    if(payload.subject_kind==='vehicle')assert(vehicles.some(v=>v.id===payload.vehicle_id));else assert.equal(payload.vehicle_id,null);assert.equal(payload.expires_on,null);
    const doc={id:docs.length+1,...payload,subject_name:'TEST11',version:0,review_state:'pending',expiry_status:'no_date',file_name:null};docs.push(doc);body={id:doc.id,version:0};
   }else if(url.pathname==='/ops/files/documents'){
    const items=docs.filter(doc=>!url.searchParams.has('subject_kind')||doc.subject_kind===url.searchParams.get('subject_kind'));body={items,total:items.length,offset:0,limit:50};
   }else if(/\/ops\/files\/documents\/\d+\/versions$/.test(url.pathname)){
    const id=+url.pathname.split('/')[4],doc=docs.find(doc=>doc.id===id);
    if(options.method==='POST'){
     assert(options.body instanceof w.File,'Upload sends the selected file, not JSON');assert.equal(options.headers['Content-Type'],'application/pdf');assert.equal(options.headers['X-PAGDOC-CSRF'],'fictitious-csrf');
     if(rejectUpload||url.searchParams.get('file_name')===rejectName){status=422;body={detail:'Fictitious antivirus rejection'};}
     else{assert.equal(+url.searchParams.get('expected_version'),doc.version);doc.version++;doc.file_name=url.searchParams.get('file_name');body={version:doc.version,review_state:'pending'};}
    }else body=Array.from({length:doc.version},(_,i)=>({version:i+1,original_name:'fictitious.pdf',size_bytes:30,scan_engine:'fictitious-ci-scanner',created_at:'2026-01-01T00:00:00Z'}));
   }else if(url.pathname.endsWith('/download'))body=null;
   else if(url.pathname==='/ops/reviews')body=docs.map(doc=>({...doc,state:doc.review_state,version:0}));
   else body=[];
   return {ok:status<400,status,json:async()=>structuredClone(body),blob:async()=>new w.Blob(['fictitious PDF'],{type:'application/pdf'})};
  };
 }
});
const w=dom.window,d=w.document,$=id=>d.getElementById(id);
async function settle(){for(let i=0;i<256;i++)await new Promise(r=>setImmediate(r));}
async function click(selector){const element=d.querySelector(selector);assert(element,selector);element.click();await settle();}
function set(name,value){const field=$('edit-form').elements[name];assert(field,name);field.value=value;field.dispatchEvent(new w.Event('change',{bubbles:true}));}
async function submit(){$('edit-form').dispatchEvent(new w.Event('submit',{cancelable:true,bubbles:true}));for(let i=0;i<10000;i++){await new Promise(r=>setTimeout(r,1));if(!$('save').disabled||$('save').textContent==='Lote finalizado')break;}await settle();}
(async()=>{
 w.eval(fs.readFileSync(path.join(root,'assets/operations.js'),'utf8'));await settle();
 $('login-email').value=me.email;$('login-password').value='fictitious-password';$('login-form').dispatchEvent(new w.Event('submit',{cancelable:true,bubbles:true}));await settle();
 assert($('editor').open);assert($('dialog-title').textContent.includes('Tutorial'));assert($('dialog-detail').textContent.includes('Bienvenido'));
 assert(!d.querySelector('[data-action="tutorial"]'));assert($('tutorial-video').controls);assert(!$('tutorial-video').autoplay);assert($('tutorial-video').querySelector('source').src.endsWith('tutorial-overview.mp4'));assert($('dialog-detail').textContent.includes('Leer los pasos del video'));
 const firstTutorialVideo=$('tutorial-video');await firstTutorialVideo.play();await click('[data-action="guide-next"]');assert(firstTutorialVideo.paused,'Changing tutorial step pauses the previous video');assert($('dialog-detail').textContent.includes('Servicios y centros de trabajo'));assert.equal($('breadcrumb').textContent,'Servicios');
 await click('[data-action="guide-next"]');assert($('dialog-detail').textContent.includes('Planificador de personal'));assert.equal($('breadcrumb').textContent,'Planificador de personal');assert($('tutorial-video').querySelector('source').src.endsWith('tutorial-planning-write.mp4'));
 await click('[data-action="guide-next"]');assert.equal($('breadcrumb').textContent,'Empresa y vehículos');
 await click('[data-action="guide-prev"]');assert.equal($('breadcrumb').textContent,'Planificador de personal');
 $('close-dialog').click();w.localStorage.clear();await click('#refresh');assert(!$('tutorial-video'));assert(!$('editor').open,'The tutorial stays dismissed even after local browser storage is cleared');
 w.history.replaceState(null,'','/app?tutorial=ver');await click('#refresh');assert($('editor').open,'An explicit review link reopens the tutorial for an existing user');assert($('tutorial-video'));assert.equal(w.location.search,'','The review query is consumed after opening');assert(!d.querySelector('[data-action="tutorial"]'));$('close-dialog').click();await click('#refresh');assert(!$('editor').open,'Reviewing does not enable automatic replay');
 assert(d.querySelector('#shell .brand').textContent.includes('Fictitious Company'));assert(d.querySelector('#shell .brand').textContent.includes('Gestionado con PAGDOC'));
 await click('[data-view="files"]');assert($('view').textContent.includes('Empresa y vehículos'));assert($('view').textContent.includes('0 documentos'));
 await click('[data-action="file-new-doc"]');assert($('edit-form').elements.vehicle_id.disabled);
 set('title','Fictitious vehicle document');set('subject_kind','vehicle');assert(!$('edit-form').elements.vehicle_id.disabled);set('vehicle_id','1');await submit();
 assert(!$('editor').open);assert($('view').textContent.includes('Fictitious vehicle document'));assert($('view').textContent.includes('Sin archivo'));
 await click('[data-action="file-upload"]');const field=$('edit-form').elements.upload_file;
 Object.defineProperty(field,'files',{value:[new w.File(['%PDF-1.7 fictitious'],'fictitious.pdf',{type:'application/pdf'})],configurable:true});
 rejectUpload=true;await submit();assert($('editor').open);assert($('form-error').textContent.includes('Fictitious antivirus rejection'));assert.equal(docs[0].version,0);
 rejectUpload=false;await submit();assert(!$('editor').open);assert.equal(docs[0].version,1);assert($('view').textContent.includes('Versión 1'));assert.equal(docs[0].review_state,'pending');
 await click('[data-action="file-history"]');assert($('dialog-detail').textContent.includes('fictitious-ci-scanner'));await click('[data-action="file-download"]');assert.deepEqual(downloads,['fictitious.pdf']);
 $('close-dialog').click();await click('[data-action="file-batch"]');
 const batchField=$('edit-form').elements.upload_files;
 const choose=(files)=>{Object.defineProperty(batchField,'files',{value:files,configurable:true});batchField.dispatchEvent(new w.Event('change',{bubbles:true}));};
 choose([new w.File(['zip'],'archive.zip')]);$('edit-form').elements.confirm_destination.checked=true;
 let before=docs.length;await submit();assert.equal(docs.length,before);assert($('form-error').textContent.includes('Usa PDF'));assert(!$('save').disabled);
 $('batch-clear').click();choose([new w.File(['%PDF-one'],'batch-one.pdf',{type:'application/pdf'}),new w.File(['%PDF-two'],'batch-two.pdf',{type:'application/pdf'})]);
 assert($('batch-preview').textContent.includes('2 archivos'));await submit();assert.equal(docs.length,before);assert($('form-error').textContent.includes('Confirma'));
 $('edit-form').elements.confirm_destination.checked=true;await submit();assert(!$('editor').open);assert.equal(docs.length,before+2);assert(docs.slice(-2).every(doc=>doc.version===1&&doc.expires_on===null&&doc.review_state==='pending'));assert($('message').textContent.includes('2 archivos guardados'));
 await click('[data-action="file-batch"]');set('subject_kind','vehicle');const vf=$('edit-form').elements.upload_files;
 Object.defineProperty(vf,'files',{value:['partial-one.pdf','blocked.pdf','not-attempted.pdf'].map(name=>new w.File(['%PDF-fiction'],name,{type:'application/pdf'})),configurable:true});
 vf.dispatchEvent(new w.Event('change',{bubbles:true}));$('edit-form').elements.confirm_destination.checked=true;before=docs.length;await submit();assert.equal(docs.length,before);assert($('form-error').textContent.includes('vehículo válido'));
 set('vehicle_id','1');$('edit-form').elements.confirm_destination.checked=true;rejectName='blocked.pdf';await submit();
 assert($('editor').open);assert.equal(docs.length,before+1);assert.equal(docs.at(-1).version,1);assert($('save').disabled);assert($('batch-preview').textContent.includes('sin intentar: 1'));assert($('form-error').textContent.includes('No vuelvas a cargar el lote completo'));
 await submit();assert.equal(docs.length,before+1);rejectName='';$('close-dialog').click();
 function directoryFile(path,content='%PDF-fictitious'){const file=new w.File([content],path.split('/').at(-1),{type:'application/pdf'});Object.defineProperty(file,'webkitRelativePath',{value:path});return file;}
 function addFolders(files){const input=$('edit-form').elements.upload_folders;Object.defineProperty(input,'files',{value:files,configurable:true});input.dispatchEvent(new w.Event('change',{bubbles:true}));}
 await click('[data-action="file-batch"]');assert($('edit-form').elements.upload_folders.hasAttribute('webkitdirectory'));assert(!$('edit-form').elements.upload_files.required);
 addFolders([directoryFile('Company/Legal/same-name.pdf')]);addFolders([directoryFile('Company/Safety/same-name.pdf')]);assert($('batch-preview').textContent.includes('2 archivos'));assert($('batch-preview').textContent.includes('Company/Safety/same-name.pdf'));
 addFolders([directoryFile('Company/Legal/same-name.pdf')]);assert($('form-error').textContent.includes('ya está seleccionada'));assert($('batch-preview').textContent.includes('2 archivos'));
 $('edit-form').elements.confirm_destination.checked=true;before=docs.length;await submit();assert.equal(docs.length,before+2);assert.deepEqual(docs.slice(-2).map(d=>d.title),['Company/Legal/same-name.pdf','Company/Safety/same-name.pdf']);assert(docs.slice(-2).every(doc=>doc.vehicle_id===null&&doc.version===1));
 await click('[data-action="file-batch"]');addFolders([directoryFile('Company/Legal/same-name.pdf')]);before=docs.length;$('edit-form').elements.confirm_destination.checked=true;await submit();assert.equal(docs.length,before);assert($('message').textContent.includes('1 idénticos omitidos'));
 await click('[data-action="file-batch"]');addFolders([directoryFile('Company/Legal/same-name.pdf','%PDF-updated')]);$('edit-form').elements.confirm_destination.checked=true;await submit();assert($('editor').open);assert($('batch-warning').textContent.includes('Advertencia'));assert.equal(docs.find(d=>d.title==='Company/Legal/same-name.pdf').version,1);await submit();assert($('form-error').textContent.includes('Confirma la advertencia'));$('edit-form').elements.confirm_replacements.checked=true;await submit();assert(!$('editor').open);assert.equal(docs.find(d=>d.title==='Company/Legal/same-name.pdf').version,2);assert.equal(docs.length,before);
 await click('[data-action="file-batch"]');addFolders([directoryFile('Company/A/remove.pdf'),directoryFile('Company/B/keep.pdf')]);await click('[data-batch-remove="0"]');assert(!$('batch-preview').textContent.includes('remove.pdf'));assert($('batch-preview').textContent.includes('keep.pdf'));$('batch-clear').click();assert($('batch-preview').textContent.includes('0 archivos'));
 addFolders([directoryFile('Company/../unsafe.pdf')]);assert($('form-error').textContent.includes('ruta'));assert($('batch-preview').textContent.includes('0 archivos'));$('close-dialog').click();
 vehicles.push({id:2,label:'Other fictitious truck',plate:'TEST22'});await click('[data-view="files"]');await click('[data-action="file-batch"]');set('subject_kind','vehicle');
 addFolders([directoryFile('Fleet/Folder-A/registration.pdf'),directoryFile('Fleet/Folder-B/registration.pdf')]);assert($('edit-form').elements.vehicle_id.disabled);before=docs.length;$('edit-form').elements.confirm_destination.checked=true;await submit();assert.equal(docs.length,before);assert($('form-error').textContent.includes('cada carpeta'));
 set('folder_vehicle_0','1');set('folder_vehicle_1','2');assert(!$('edit-form').elements.confirm_destination.checked);$('edit-form').elements.confirm_destination.checked=true;await submit();assert.equal(docs.length,before+2);assert.deepEqual(docs.slice(-2).map(d=>d.vehicle_id),[1,2]);
 await click('[data-action="file-batch"]');addFolders(Array.from({length:51},(_,i)=>directoryFile('Company/Archive/fictitious-'+i+'.pdf')));before=docs.length;$('edit-form').elements.confirm_destination.checked=true;await submit();assert.equal(docs.length,before+51);assert($('message').textContent.includes('51 archivos guardados'));
 await click('[data-action="file-batch"]');before=docs.length;addFolders(Array.from({length:251},(_,i)=>directoryFile('Company/Large/fictitious-'+i+'.pdf')));assert($('form-error').textContent.includes('250'));assert($('batch-preview').textContent.includes('0 archivos'));assert.equal(docs.length,before);$('close-dialog').click();
 await click('[data-view="security"]');assert($('view').textContent.includes('Alertas por correo'));await click('[data-action="email-preferences"]');set('enabled','1');set('days_before','7');await submit();assert(emailPref.enabled);assert.equal(emailPref.days_before,7);assert($('view').textContent.includes('Activadas en tu perfil'));await click('[data-action="email-preview"]');assert($('dialog-detail').textContent.includes('Tareas atrasadas: 3'));assert($('dialog-detail').textContent.includes('no envía correos'));$('close-dialog').click();await click('[data-action="file-logo"]');const logoField=$('edit-form').elements.upload_file;
 Object.defineProperty(logoField,'files',{value:[new w.File(['fictitious PNG'],'fictitious.png',{type:'image/png'})],configurable:true});await submit();
 assert.equal(logoVersion,1);assert.equal($('company-logo').getAttribute('src'),'/ops/branding/logo?v=1');assert(!$('editor').open);
 $('logout').click();await settle();assert(!d.querySelector('#shell .brand').classList.contains('company-brand'));assert(!d.querySelector('#company-logo'));
 assert(calls.every(call=>call.options.credentials==='same-origin'));assert.deepEqual(errors,[]);
 console.log('Private files UI: files, accumulated folders, nested paths, per-folder vehicle binding, 51-file upload, rejection handling and private branding: OK');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>dom.window.close());
