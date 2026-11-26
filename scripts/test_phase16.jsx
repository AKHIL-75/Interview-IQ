import test, { beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { create, act } from 'react-test-renderer';
import api from '../src/services/client.js';
import ErrorBoundary from '../src/components/ErrorBoundary.jsx';
import FileUpload from '../src/components/FileUpload.jsx';

const originalFetch = globalThis.fetch;
let signs, refreshes;
beforeEach(() => {
  signs = refreshes = 0;
  globalThis.auth = { token: 'test-token', refresh: async () => {
    refreshes++; return { data: { session: { access_token: 'renewed' } } };
  }, signOut: async () => { signs++; } };
});
afterEach(() => { globalThis.fetch = originalFetch; });
const response = (status, data, headers={}) => new Response(JSON.stringify(data), { status, headers });

test('offline POST is not retried and reports a friendly message', async () => {
  let calls=0;
  globalThis.fetch=async()=>{calls++;throw new TypeError('Failed to fetch private-host');};
  await assert.rejects(api.post('/evaluation/evaluate',{answer:'kept'}), /Unable to reach the interview service/);
  assert.equal(calls,1); assert.equal(signs,0);
});

test('server failure does not expose internal detail or retry POST', async () => {
  let calls=0;
  globalThis.fetch=async()=>{calls++;return response(500,{detail:'private secret stack'});};
  await assert.rejects(api.post('/evaluation/evaluate',{}), e=>e.status===500 && !e.message.includes('secret'));
  assert.equal(calls,1);
});

test('one 401 refresh replays exactly the same edited answer', async () => {
  const bodies=[];
  globalThis.fetch=async(_,opts)=>{ bodies.push(opts.body); assert.equal('_retry' in opts,false);
    return bodies.length===1 ? response(401,{}) : response(200,{saved:true}); };
  assert.deepEqual(await api.post('/evaluation/evaluate',{answer:'edited by candidate'}),{saved:true});
  assert.equal(bodies.length,2);assert.equal(bodies[0],bodies[1]);assert.equal(refreshes,1);
});

test('audio upload refresh reuses the exact multipart body and submits no duplicate successful request', async () => {
  const body = new FormData(); body.append('file', new Blob(['synthetic audio']), 'synthetic.wav');
  const requests = [];
  globalThis.auth.refresh = async () => {
    refreshes++; globalThis.auth.token = 'renewed';
    return { data: { session: { access_token: 'renewed' } } };
  };
  globalThis.fetch = async (_, options) => {
    requests.push(options);
    assert.equal(options.body, body);
    assert.equal('Content-Type' in options.headers, false);
    return requests.length === 1 ? response(401, {}) : response(200, { success: true, text: 'Quartz Harbor 47.' });
  };
  assert.deepEqual(await api.upload('/audio/transcribe', body, { timeoutMs: 660000 }), { success: true, text: 'Quartz Harbor 47.' });
  assert.equal(requests.length, 2); assert.equal(refreshes, 1); assert.equal(signs, 0);
  assert.equal(requests[0].headers.Authorization, 'Bearer test-token');
  assert.equal(requests[1].headers.Authorization, 'Bearer renewed');
});

test('failed retried evaluation is not treated as a failed token refresh', async () => {
  let calls=0;
  globalThis.fetch=async()=>response(++calls===1?401:503,{});
  await assert.rejects(api.post('/evaluation/evaluate',{}),e=>e.status===503);
  assert.equal(calls,2);assert.equal(signs,0);assert.equal(refreshes,1);
});

test('refresh outage preserves auth state', async () => {
  globalThis.fetch=async()=>response(401,{});
  globalThis.auth.refresh=async()=>{throw new TypeError('offline');};
  await assert.rejects(api.post('/evaluation/evaluate',{}),/Unable to refresh/);
  assert.equal(signs,0);
});

test('second 401 ends retry loop',async()=>{
  let calls=0;globalThis.fetch=async()=>{calls++;return response(401,{detail:'Sign in again'});};
  await assert.rejects(api.post('/evaluation/evaluate',{}),e=>e.status===401);
  assert.equal(calls,2);assert.equal(refreshes,1);assert.equal(signs,1);
});

test('rate limit exposes retry delay without auto-retry',async()=>{
  let calls=0;globalThis.fetch=async()=>{calls++;return response(429,{}, {'Retry-After':'60'});};
  await assert.rejects(api.post('/audio/transcribe',{}),e=>e.status===429 && e.retryAfter==='60');
  assert.equal(calls,1);
});

test('malformed successful response fails recoverably',async()=>{
  globalThis.fetch=async()=>new Response('not json',{status:200});
  await assert.rejects(api.post('/evaluation/evaluate',{}),/unreadable response/);
});

test('timeout remains active until response body completes',async()=>{
  const set=globalThis.setTimeout, clear=globalThis.clearTimeout;
  let fire, cleared=false;
  globalThis.setTimeout=(cb)=>{fire=cb;return 123;};
  globalThis.clearTimeout=()=>{cleared=true;};
  globalThis.fetch=async(_,opts)=>({status:200,ok:true,json:()=>new Promise((_,reject)=>{
    assert.equal(cleared,false);
    opts.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')));
    fire();
  })});
  try { await assert.rejects(api.post('/evaluation/evaluate',{}),/timed out/);assert.equal(cleared,true); }
  finally {globalThis.setTimeout=set;globalThis.clearTimeout=clear;}
});

test('error boundary renders recovery and reload does not clear storage',()=>{
  const old=console.error;console.error=()=>{};
  let reloads=0;globalThis.window={location:{reload:()=>reloads++}};
  function Broken(){throw new Error('sensitive render detail');}
  let root;
  try {act(()=>{root=create(<ErrorBoundary><Broken/></ErrorBoundary>);});
    assert.equal(root.root.findByProps({role:'alert'}).type,'main');
    assert.ok(!JSON.stringify(root.toJSON()).includes('sensitive'));
    act(()=>root.root.findByType('button').props.onClick());assert.equal(reloads,1);
    root.unmount();
  }finally{console.error=old;delete globalThis.window;}
});

test('file picker rejects invalid size/type before calling API',async()=>{
  let calls=0,root;act(()=>{root=create(<FileUpload onFileSelect={()=>calls++}/>);});
  await act(async()=>root.root.findByType('input').props.onChange({target:{files:[{name:'resume.exe',size:100}]}}));
  assert.equal(calls,0);assert.match(root.root.findByProps({role:'alert'}).children.join(''),/PDF or DOCX/);
  root.unmount();
});
