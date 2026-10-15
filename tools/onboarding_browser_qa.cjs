/* Loopback-only fixtures. Fake camera/microphone are NOT hardware validation. */
'use strict';
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
const OUTPUT=process.env.WEWATCH_QA_DIR;if(!OUTPUT)throw new Error('Set private WEWATCH_QA_DIR');
const BASE='http://127.0.0.1:5002', PASSWORD='phase-two-fixture-passphrase';
const PREVIEWS=path.join(OUTPUT,'phase2-previews');fs.mkdirSync(PREVIEWS,{recursive:true,mode:0o700});
const results=[],errors=[],urls=[];
function record(test,pass){results.push({test,pass:!!pass});if(!pass)throw new Error('Failed: '+test);}
function tokenFor(recipient){
 const dir=path.join(OUTPUT,'outbox');
 const files=fs.readdirSync(dir).map(name=>({name,at:fs.statSync(path.join(dir,name)).mtimeMs})).sort((a,b)=>b.at-a.at);
 for(const file of files){const text=fs.readFileSync(path.join(dir,file.name),'utf8').replace(/=\r?\n/g,'').replace(/=3D/g,'=');if(text.includes('To: '+recipient)){const token=text.match(/#token=([A-Za-z0-9_-]+)/)?.[1];if(token)return token;}}
 throw new Error('Fixture mail missing');
}
async function post(context,url,data={}){
 const csrf=(await (await context.request.get(BASE+'/api/session')).json()).csrf_token;
 return context.request.post(BASE+url,{data,headers:{'X-CSRF-Token':csrf}});
}
async function account(context,email,name){
 let r=await post(context,'/register',{email,password:PASSWORD,display_name:name});if(r.status()!==200)throw new Error('Register '+r.status());
 r=await post(context,'/verify-email',{token:tokenFor(email)});if(r.status()!==200)throw new Error('Verify');
 r=await post(context,'/login',{email,password:PASSWORD});if(r.status()!==200)throw new Error('Login');
 return (await (await context.request.get(BASE+'/api/me')).json()).user.id;
}
async function snapshot(page,name){
 let html=await page.evaluate(()=>{const clone=document.documentElement.cloneNode(true);clone.querySelectorAll('script').forEach(node=>node.remove());clone.querySelectorAll('input').forEach(node=>{if(node.id==='pair-token')node.setAttribute('value','[token fixture disembunyikan]');});return '<!doctype html>'+clone.outerHTML;});html=html.replace(/(href|src)="\/assets\/((?:platform|onboarding)\.(?:css|js))"/g,(_,attr,file)=>`${attr}="file://${path.resolve(__dirname,'../platform_static',file)}"`);
 fs.writeFileSync(path.join(PREVIEWS,name+'.html'),html);
}
async function stopped(page,kind){await page.waitForFunction(k=>document.getElementById(k+'-state').textContent.startsWith('Tidak aktif'),kind);}
async function active(page,kind){await page.waitForFunction(k=>document.getElementById(k+'-state').textContent.startsWith('AKTIF'),kind);}
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true,args:['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
 try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['camera','microphone'],colorScheme:'light'});
 await context.addInitScript(()=>{
  window.__qaMediaCalls=0;window.__qaTracks=[];
  const gum=navigator.mediaDevices?.getUserMedia.bind(navigator.mediaDevices);
  if(gum){window.__qaOriginalGUM=gum;navigator.mediaDevices.getUserMedia=async constraints=>{window.__qaMediaCalls++;const stream=await gum(constraints);window.__qaTracks.push(...stream.getTracks());return stream;};}
 });
 context.on('request',r=>urls.push(r.url()));
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await account(context,'phase2-owner@example.com','Dimas QA');
 const ws=(await (await post(context,'/workspaces',{name:'Tim Onboarding'})).json()).workspace_id;
 const onboard=`/workspaces/${ws}/onboarding`;
 await page.goto(BASE+onboard);await snapshot(page,'onboarding-unpaired');
 record('onboarding page load requests no media',await page.evaluate(()=>window.__qaMediaCalls===0));
 await page.getByLabel('Nama sesi browser').fill('Laptop QA');await page.getByRole('button',{name:'Buat token pairing'}).click();
 await page.waitForFunction(()=>document.getElementById('pair-token').value.length>20);
 const raw=await page.locator('#pair-token').inputValue();await snapshot(page,'onboarding-pending');
 record('pair request does not grant camera or microphone',(await (await context.request.get(BASE+`/api/workspaces/${ws}/onboarding`)).json()).grants.length===0);
 await page.getByRole('link',{name:'Tinjau & konfirmasi'}).click();await page.waitForFunction(()=>location.hash==='');
 record('pairing fragment removed without automatic approval',!(await (await context.request.get(BASE+`/api/workspaces/${ws}/onboarding`)).json()).device);
 await page.getByRole('button',{name:'Periksa permintaan'}).click();await page.locator('#pair-approval-details').waitFor({state:'visible'});await snapshot(page,'pairing-review');
 await page.getByRole('button',{name:'Saya mengenali sesi ini · Setujui pairing'}).click();await page.waitForFunction(()=>document.getElementById('approval-message').textContent.includes('Pairing disetujui'));
 await page.getByRole('link',{name:'Kembali ke browser onboarding'}).click();await snapshot(page,'onboarding-paired');
 let status=await (await context.request.get(BASE+`/api/workspaces/${ws}/onboarding`)).json();const device=status.device.id;
 record('pairing binds current browser but gives no media grant',!!device&&status.grants.length===0&&await page.evaluate(()=>window.__qaMediaCalls===0));
 await page.getByRole('button',{name:'Periksa tanpa membuka media'}).click();await page.waitForFunction(()=>document.getElementById('onboarding-message').textContent.includes('Pemeriksaan selesai'));
 record('readiness check never opens media',await page.evaluate(()=>window.__qaMediaCalls===0));
 await page.getByRole('button',{name:'Izinkan & preview kamera'}).click();await active(page,'camera');await snapshot(page,'onboarding-camera');
 status=await (await context.request.get(BASE+`/api/workspaces/${ws}/onboarding`)).json();
 record('camera permission leaves microphone off',status.grants.length===1&&status.grants[0].capability==='camera_preview'&&await page.evaluate(()=>!document.getElementById('microphone-state').textContent.startsWith('AKTIF')));
 await page.getByRole('button',{name:'Izinkan & uji mikrofon'}).click();await active(page,'microphone');
 record('separate microphone button adds only audio consent',(await (await context.request.get(BASE+`/api/workspaces/${ws}/onboarding`)).json()).grants.length===2);
 await page.getByRole('button',{name:'Hentikan kamera',exact:true}).click();await stopped(page,'camera');
 record('camera stop does not stop microphone',await page.evaluate(()=>window.__qaTracks.filter(t=>t.kind==='video').every(t=>t.readyState==='ended')&&window.__qaTracks.some(t=>t.kind==='audio'&&t.readyState==='live')));
 await page.getByRole('button',{name:/STOP ·/}).click();await stopped(page,'microphone');
 record('emergency stop ends all local tracks synchronously',await page.evaluate(()=>window.__qaTracks.every(t=>t.readyState==='ended')));
 await page.waitForTimeout(150);
 record('emergency stop revokes both server grants',(await (await context.request.get(BASE+`/api/workspaces/${ws}/onboarding`)).json()).grants.length===0);
 await page.evaluate(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Fixture permission denied','NotAllowedError');};});
 await page.getByRole('button',{name:'Izinkan & preview kamera'}).click();await page.waitForFunction(()=>document.getElementById('check-camera').textContent==='Izin ditolak');await snapshot(page,'onboarding-denied');
 await page.waitForTimeout(150);
 record('permission denied fails closed and revokes intent',(await (await context.request.get(BASE+`/api/workspaces/${ws}/onboarding`)).json()).grants.length===0);
 await page.evaluate(()=>{navigator.mediaDevices.getUserMedia=async constraints=>{window.__qaMediaCalls++;const stream=await window.__qaOriginalGUM(constraints);window.__qaTracks.push(...stream.getTracks());return stream;};});
 await page.getByRole('button',{name:'Izinkan & preview kamera'}).click();await active(page,'camera');
 await context.setOffline(true);await stopped(page,'camera');
 record('offline event stops tracks',await page.evaluate(()=>window.__qaTracks.every(t=>t.readyState==='ended')));
 await context.setOffline(false);await page.waitForTimeout(4200);
 record('online recovery never auto-restarts camera',await page.evaluate(()=>!document.getElementById('camera-state').textContent.startsWith('AKTIF')));
 await page.getByRole('button',{name:'Izinkan & preview kamera'}).click();await active(page,'camera');
 // Deterministic DOM lifecycle signal: verifies handler, not OS/background scheduling.
 await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide')));await stopped(page,'camera');
 record('pagehide handler stops all local tracks',await page.evaluate(()=>window.__qaTracks.every(t=>t.readyState==='ended')));
 await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pageshow')));
 await page.setViewportSize({width:390,height:844});await snapshot(page,'onboarding-mobile');
 record('mobile onboarding has no horizontal page overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('button',{name:'Izinkan & preview kamera'}).click();await active(page,'camera');
 const manager=await browser.newContext();await post(manager,'/login',{email:'phase2-owner@example.com',password:PASSWORD});
 record('remote revocation request by same owner succeeds',(await post(manager,`/workspaces/${ws}/devices/${device}/revoke`)).status()===200);
 await stopped(page,'camera');
 record('polling notices revoked pairing and stops all tracks',await page.evaluate(()=>window.__qaTracks.every(t=>t.readyState==='ended')));
 await page.goto(BASE+onboard);await snapshot(page,'onboarding-revoked');
 const memberContext=await browser.newContext({viewport:{width:1440,height:1000}});
 const uid=await account(memberContext,'phase2-member@example.com','Rani QA');
 await post(context,`/workspaces/${ws}/invitations`,{email:'phase2-member@example.com',role:'viewer'});
 await post(memberContext,'/invitations/accept',{token:tokenFor('phase2-member@example.com')});
 const memberPage=await memberContext.newPage();await memberPage.goto(BASE+onboard);await snapshot(memberPage,'onboarding-viewer');
 record('Viewer has no enrollment form and no grant controls',await memberPage.locator('#pair-form').count()===0&&await memberPage.locator('#camera-start').isDisabled());
 await memberPage.setViewportSize({width:390,height:844});await snapshot(memberPage,'onboarding-viewer-mobile');
 record('mobile Viewer has no horizontal page overflow',await memberPage.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 const outsider=await browser.newContext();await account(outsider,'phase2-outsider@example.com','Outsider QA');
 record('foreign workspace onboarding rejected',(await outsider.request.get(BASE+onboard)).status()===404);
 record('another account cannot inspect consumed or foreign pairing',(await post(outsider,'/device-pairing/inspect',{token:raw})).status()===404);
 record('no pairing bearer is sent in any HTTP URL',urls.every(url=>!url.includes(raw)&&!url.includes('#token=')));
 record('onboarding requests no third-party hosts',urls.every(url=>url.startsWith(BASE+'/')));
 record('no browser runtime errors',errors.length===0);
 fs.writeFileSync(path.join(OUTPUT,'phase2-browser-results.json'),JSON.stringify({results,runtimeErrors:errors,scope:'Loopback SQLite/accounts/file-mail + Chromium fake media; no real hardware, SMTP, Windows, remote control, or production'},null,2));
 console.log(JSON.stringify({passed:results.filter(r=>r.pass).length,total:results.length,runtimeErrors:errors.length}));
 }finally{await browser.close();}
})().then(()=>process.exit(0)).catch(error=>{console.error(error);process.exit(1);});
