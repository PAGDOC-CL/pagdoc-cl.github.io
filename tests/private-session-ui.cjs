const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {JSDOM, VirtualConsole} = require('jsdom');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'operacion.html'), 'utf8').replace('data-runtime="demo"', 'data-runtime="private"');
const source = fs.readFileSync(path.join(root, 'assets/operations.js'), 'utf8');
const errors = [], calls = [];
let authenticated = false, forbidden = false;
const me = {id: 1, email: 'admin@example.invalid', role: 'admin', mfa_enabled: false, capabilities: ['plan.read', 'tasks.read']};
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push(e.message));
const dom = new JSDOM(html, {
  url: 'https://localhost:8443/app', runScripts: 'dangerously', virtualConsole: vc,
  beforeParse(w) {
    w.structuredClone = structuredClone;
    w.HTMLMediaElement.prototype.play=async function(){Object.defineProperty(this,'paused',{value:false,configurable:true});};w.HTMLMediaElement.prototype.pause=function(){Object.defineProperty(this,'paused',{value:true,configurable:true});};
    w.HTMLDialogElement.prototype.showModal = function() {this.open = true;};
    w.HTMLDialogElement.prototype.close = function() {this.open = false;};
    w.fetch = async (url, options) => {
      calls.push({url, options});
      let status = 200, body;
      if(url==='/login/branding'){body={logo_version:0};}
      else if (url === '/auth/login') {
        const credentials = JSON.parse(options.body);
        if (credentials.password === 'invalid') {status = 401; body = {detail: 'Invalid credentials'};}
        else {authenticated = true; body = {authenticated: true};}
      } else if (!authenticated) {status = 401; body = {detail: 'Authentication required'};}
      else if (forbidden) {status = 403; body = {detail: 'Permission denied'};}
      else if (url === '/ops/bootstrap') body = {me, tenant: {id: 1, name: 'Fictitious tenant'}, workers: [], projects: [], users: []};
      else if (url === '/ops/dashboard') body = {active_services: 0, pending_tasks: 0, overdue_tasks: 0, tomorrow_assignments: 0, tomorrow_blocked: 0};
      else if (url === '/ops/integrations') body = {};
      else body = [];
      return {ok: status < 400, status, json: async () => structuredClone(body)};
    };
  }
});
const w = dom.window, d = w.document, $ = id => d.getElementById(id);
async function settle() {for (let i = 0; i < 5; i++) await new Promise(r => setImmediate(r));}
async function login(password) {
  $('login-email').value = me.email;
  $('login-password').value = password;
  $('login-form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await settle();
}
(async () => {
  w.eval(source);
  await settle();
  assert(!$('login').hidden);
  assert($('shell').hidden);
  assert.equal($('login-film').getAttribute('src'),'/app/assets/operations-film.mp4');assert($('login-film').muted);assert($('login-film').loop);
  $('film-toggle').click();await settle();assert.equal($('login-film').paused,false);assert.equal($('film-toggle').textContent,'Pausar imágenes');
  $('film-toggle').click();await settle();assert.equal($('login-film').paused,true);
  assert.equal($('message').textContent, '', 'Initial 401 belongs to the sign-in screen');
  await login('invalid');
  assert.equal($('login-error').textContent, 'Invalid credentials');
  assert($('shell').hidden, 'Rejected login never opens workspace');
  await login('fictitious-test-password');
  assert(!$('shell').hidden);
  assert($('login').hidden);assert.equal($('login-film').paused,true);
  assert.equal($('message').textContent, '');
  assert.equal($('login-password').value, '');
  assert.equal($('tenant-name').textContent, 'Fictitious tenant');
  forbidden = true;
  $('refresh').click(); await settle();
  assert.equal($('message').textContent, 'Permission denied', 'Real authorization failures remain visible');
  forbidden = false;
  $('refresh').click(); await settle();
  assert.equal($('message').textContent, '', 'Successful reload clears obsolete errors');
  authenticated = false;
  $('refresh').click(); await settle();
  assert(!$('login').hidden);
  assert($('shell').hidden, 'Expired session hides private workspace');
  assert.equal($('message').textContent, '');
  assert(calls.every(c => c.options.credentials === 'same-origin'));
  assert.deepEqual(errors, []);
  console.log('Private UI: initial sign-in, rejected credentials, session recovery, real errors and expiration: OK');
})().catch(e => {console.error(e); process.exitCode = 1;}).finally(() => dom.window.close());
