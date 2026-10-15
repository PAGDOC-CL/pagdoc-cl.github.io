const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'..'),errors=[],calls=[],downloads=[];
const docs=[],vehicles=[{id:1,label:'Fictitious truck',plate:'TEST11'}];
let signedIn=false,rejectUpload=false;
const me={id:1,email:'admin@example.invalid',role:'admin',capabilities:['plan.read','plan.write','documents.read','documents.write','documents.review','tasks.read','tasks.write','users.manage']};
const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(fs.readFileSync(path.join(root,'operacion.html'),'utf8').replace('data-runtime="demo"','data-runtime="private"'),{
 url:'https://localhost:8443/app',runScripts:'dangerously',virtualConsole:vc,beforeParse(w){
  w.structuredClone=structuredClone;w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.URL.createObjectURL=()=> 'blob:fictitious-private-download';w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){downloads.push(this.download);};
  w.fetch=async(route,options)=>{
   calls.push({route,options});const url=new URL(route,'https://localhost:8443');let status=200,body;
   const payload=typeof options.body==='string'?JSON.parse(options.body):null;
   if(url.pathname==='/auth/login'){signedIn=true;w.document.cookie='pagdoc_csrf=fictitious-csrf; Path=/; Secure; SameSite=Strict';body={authenticated:true};}
   else if(!signedIn){status=401;body={detail:'Authentication required'};}
   else if(url.pathname==='/ops/bootstrap')body={me,tenant:{id:1,name:'Fictitious Company'},workers:[],projects:[],users:[]};
   else if(url.pathname==='/ops/dashboard')body={active_services:0,pending_tasks:0,overdue_tasks:0,tomorrow_assignments:0,tomorrow_blocked:0};
   else if(url.pathname==='/ops/integrations')body={storage:{binary_http_enabled:true}};
   else if(url.pathname==='/ops/files/status')body={enabled:true,ready_for_upload:true,max_bytes:15*1024*1024};
   else if(url.pathname==='/ops/files/subjects')body={company:'Fictitious Company',vehicles};
   else if(url.pathname==='/ops/files/documents'&&options.method==='POST'){
    assert.equal(payload.vehicle_id,1);assert.equal(payload.subject_kind,'vehicle');assert.equal(payload.expires_on,null);
    const doc={id:docs.length+1,...payload,subject_name:'TEST11',version:0,review_state:'pending',expiry_status:'no_date',file_name:null};docs.push(doc);body={id:doc.id,version:0};
   }else if(url.pathname==='/ops/files/documents'){
    const items=docs.filter(doc=>!url.searchParams.has('subject_kind')||doc.subject_kind===url.searchParams.get('subject_kind'));body={items,total:items.length,offset:0,limit:50};
   }else if(/\/ops\/files\/documents\/\d+\/versions$/.test(url.pathname)){
    const id=+url.pathname.split('/')[4],doc=docs.find(doc=>doc.id===id);
    if(options.method==='POST'){
     assert(options.body instanceof w.File,'Upload sends the selected file, not JSON');assert.equal(options.headers['Content-Type'],'application/pdf');assert.equal(options.headers['X-PAGDOC-CSRF'],'fictitious-csrf');
     if(rejectUpload){status=422;body={detail:'Fictitious antivirus rejection'};}
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
async function settle(){for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));}
async function click(selector){const element=d.querySelector(selector);assert(element,selector);element.click();await settle();}
function set(name,value){const field=$('edit-form').elements[name];assert(field,name);field.value=value;field.dispatchEvent(new w.Event('change',{bubbles:true}));}
async function submit(){$('edit-form').dispatchEvent(new w.Event('submit',{cancelable:true,bubbles:true}));await settle();}
(async()=>{
 w.eval(fs.readFileSync(path.join(root,'assets/operations.js'),'utf8'));await settle();
 $('login-email').value=me.email;$('login-password').value='fictitious-password';$('login-form').dispatchEvent(new w.Event('submit',{cancelable:true,bubbles:true}));await settle();
 await click('[data-view="files"]');assert($('view').textContent.includes('Empresa y vehículos'));assert($('view').textContent.includes('0 documentos'));
 await click('[data-action="file-new-doc"]');assert($('edit-form').elements.vehicle_id.disabled);
 set('title','Fictitious vehicle document');set('subject_kind','vehicle');assert(!$('edit-form').elements.vehicle_id.disabled);set('vehicle_id','1');await submit();
 assert(!$('editor').open);assert($('view').textContent.includes('Fictitious vehicle document'));assert($('view').textContent.includes('Sin archivo'));
 await click('[data-action="file-upload"]');const field=$('edit-form').elements.upload_file;
 Object.defineProperty(field,'files',{value:[new w.File(['%PDF-1.7 fictitious'],'fictitious.pdf',{type:'application/pdf'})],configurable:true});
 rejectUpload=true;await submit();assert($('editor').open);assert($('form-error').textContent.includes('Fictitious antivirus rejection'));assert.equal(docs[0].version,0);
 rejectUpload=false;await submit();assert(!$('editor').open);assert.equal(docs[0].version,1);assert($('view').textContent.includes('Versión 1'));assert.equal(docs[0].review_state,'pending');
 await click('[data-action="file-history"]');assert($('dialog-detail').textContent.includes('fictitious-ci-scanner'));await click('[data-action="file-download"]');assert.deepEqual(downloads,['fictitious.pdf']);
 assert(calls.every(call=>call.options.credentials==='same-origin'));assert.deepEqual(errors,[]);
 console.log('Private files UI: explicit vehicle selection, pending metadata, real file body, rejected upload, version history and authenticated download: OK');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>dom.window.close());
