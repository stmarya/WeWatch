'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {PreviewController}=require('../platform_static/onboarding.js');
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function stream(kind='camera'){
 const track={readyState:'live',stopped:0,handlers:{},stop(){this.stopped++;this.readyState='ended';},addEventListener(name,fn){this.handlers[name]=fn;}};
 return {track,getTracks:()=>[track],getVideoTracks:()=>kind==='camera'?[track]:[],getAudioTracks:()=>kind==='microphone'?[track]:[]};
}
function fixture(override={}){
 const events=[],timers=new Map();let clock=0,sequence=0,visible=true;
 const a={now:()=>clock,timer:(fn,ms)=>{const id=++sequence;timers.set(id,{fn,ms});return id;},clearTimer:id=>timers.delete(id),
  visible:()=>visible,grant:async kind=>{events.push('grant:'+kind);return {expires_at:700,server_time:100};},
  revoke:async kind=>events.push('revoke:'+kind),media:async kind=>{events.push('media:'+kind);return stream(kind);},
  attach:kind=>events.push('attach:'+kind),detach:kind=>events.push('detach:'+kind),changed:()=>{},report:()=>{},message:()=>{},...override};
 return {controller:new PreviewController(a),a,events,timers,setVisible:value=>visible=value,setClock:value=>clock=value};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('constructor never requests permission or media',()=>{const f=fixture();assert.deepEqual(f.events,[]);});
test('grant precedes media and explicit start attaches only chosen capability',async()=>{const f=fixture();await f.controller.start('camera');assert.deepEqual(f.events,['grant:camera','media:camera','attach:camera']);assert.equal(f.controller.state.microphone.stream,null);});
test('microphone uses its independent grant',async()=>{const f=fixture();await f.controller.start('microphone');assert.deepEqual(f.events,['grant:microphone','media:microphone','attach:microphone']);});
test('stop immediately stops track before revocation finishes',async()=>{const pending=deferred();const f=fixture({revoke:()=>pending.promise});await f.controller.start('camera');const track=f.controller.state.camera.stream.track;f.controller.stop('camera');assert.equal(track.stopped,1);assert.equal(f.controller.state.camera.stream,null);pending.resolve();});
test('STOP while OS permission prompt pending never attaches late stream',async()=>{const pending=deferred();const f=fixture({media:()=>pending.promise});const start=f.controller.start('camera');await tick();f.controller.stopAll();const late=stream();pending.resolve(late);await start;assert.equal(late.track.stopped,1);assert.ok(!f.events.includes('attach:camera'));});
test('tab hidden during permission acquisition stops late tracks',async()=>{const pending=deferred();const f=fixture({media:()=>pending.promise});const start=f.controller.start('camera');await tick();f.setVisible(false);const late=stream();pending.resolve(late);await start;assert.equal(late.track.stopped,1);assert.ok(!f.events.includes('attach:camera'));});
test('grant denied or network failure never calls media',async()=>{const f=fixture({grant:async()=>{throw new Error('offline');}});await f.controller.start('camera');assert.ok(!f.events.includes('media:camera'));assert.equal(f.controller.state.camera.pending,false);});
test('browser denial revokes the server grant',async()=>{const f=fixture({media:async()=>{throw Object.assign(new Error('denied'),{name:'NotAllowedError'});}});await f.controller.start('camera');assert.ok(f.events.includes('revoke:camera'));assert.equal(f.controller.state.camera.stream,null);});
test('expiry timer stops media without auto restart',async()=>{const f=fixture();await f.controller.start('camera');const track=f.controller.state.camera.stream.track;const expiry=[...f.timers.values()].find(t=>t.ms===600000);assert.ok(expiry);expiry.fn();assert.equal(track.stopped,1);assert.equal(f.events.filter(e=>e==='media:camera').length,1);});
test('server revocation while prompt pending stops late tracks',async()=>{const pending=deferred();const f=fixture({media:()=>pending.promise});const start=f.controller.start('camera');await tick();f.controller.reconcile([]);const late=stream();pending.resolve(late);await start;assert.equal(late.track.stopped,1);assert.ok(!f.events.includes('attach:camera'));});
test('server reconciliation independently stops only revoked capability',async()=>{const f=fixture();await f.controller.start('camera');await f.controller.start('microphone');const cam=f.controller.state.camera.stream.track;const mic=f.controller.state.microphone.stream.track;f.controller.reconcile([{capability:'microphone_preview'}]);assert.equal(cam.stopped,1);assert.equal(mic.stopped,0);});
test('grant response arriving after STOP is revoked and never opens media',async()=>{const pending=deferred();const f=fixture({grant:()=>pending.promise});const start=f.controller.start('camera');f.controller.stopAll();pending.resolve({expires_at:700,server_time:100});await start;assert.ok(!f.events.includes('media:camera'));assert.equal(f.events.filter(e=>e==='revoke:camera').length,2);});
test('duplicate clicks cannot create duplicate streams',async()=>{const pending=deferred();const f=fixture({media:()=>pending.promise});const start=f.controller.start('camera');await f.controller.start('camera');await tick();pending.resolve(stream());await start;assert.equal(f.events.filter(e=>e==='grant:camera').length,1);});
test('invalid or already expired grant fails closed',async()=>{const f=fixture({grant:async()=>({expires_at:100,server_time:100})});await f.controller.start('camera');assert.ok(!f.events.includes('media:camera'));});
test('browser track ended event stops preview and revokes consent',async()=>{const f=fixture();await f.controller.start('camera');const track=f.controller.state.camera.stream.track;track.handlers.ended();assert.equal(f.controller.state.camera.stream,null);assert.ok(f.events.includes('revoke:camera'));});
test('permission prompt timeout never attaches late result',async()=>{const pending=deferred();const f=fixture({media:()=>pending.promise});const start=f.controller.start('camera');await tick();[...f.timers.values()].find(t=>t.ms===60000).fn();const late=stream();pending.resolve(late);await start;assert.equal(late.track.stopped,1);assert.ok(!f.events.includes('attach:camera'));});
