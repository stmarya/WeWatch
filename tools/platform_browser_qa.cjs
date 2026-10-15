/* Loopback fixtures only. Uses a private file mailbox, never a real mail provider. */
'use strict';
const {chromium} = require('playwright');
const fs = require('fs'); const path = require('path');
const OUTPUT = process.env.WEWATCH_QA_DIR;
if (!OUTPUT) throw new Error('Set WEWATCH_QA_DIR to the private directory used by the QA server');
const BASE = 'http://127.0.0.1:5002';
const PASSWORD = 'phase-one-test-only-passphrase';
const PREVIEWS = path.join(OUTPUT, 'previews'); fs.mkdirSync(PREVIEWS, {recursive:true, mode:0o700});
const results = []; const runtimeErrors = []; const network = [];
function record(test, pass) { results.push({test, pass:!!pass}); }
function mailboxToken(recipient) {
    const folder = path.join(OUTPUT,'outbox');
    const files = fs.readdirSync(folder).map(name=>({name,at:fs.statSync(path.join(folder,name)).mtimeMs})).sort((a,b)=>b.at-a.at);
    for(const file of files) {
        const source = fs.readFileSync(path.join(folder,file.name),'utf8').replace(/=\r?\n/g,'').replace(/=3D/g,'=');
        if(source.includes('To: '+recipient)) {
            const token = source.match(/#token=([A-Za-z0-9_-]+)/)?.[1];
            if(token) return token;
        }
    }
    throw new Error('Fixture mailbox token missing');
}
async function snapshot(page, name) {
    let html = await page.content();
    html = html.replace(/(href|src)="\/assets\/(platform\.(?:css|js))"/g,
        (_,attribute,file)=>`${attribute}="file://${path.resolve(__dirname,'../platform_static',file)}"`);
    fs.writeFileSync(path.join(PREVIEWS,name+'.html'),html);
}
async function registerAndVerify(page, email, name) {
    await page.goto(BASE+'/register');
    await page.locator('#display-name').fill(name); await page.locator('#email').fill(email);
    await page.locator('#password').fill(PASSWORD);
    await Promise.all([page.waitForURL('**/login'),page.getByRole('button',{name:'Daftar & kirim verifikasi'}).click()]);
    const token = mailboxToken(email);
    await page.goto(BASE+'/verify-email#token='+token);
    await page.waitForFunction(()=>location.hash==='');
    record('email bearer token stays out of HTTP URL', !page.url().includes('#token='));
    await Promise.all([page.waitForURL('**/login'),page.getByRole('button',{name:'Konfirmasi email'}).click()]);
    await page.locator('#email').fill(email); await page.locator('#password').fill(PASSWORD);
    await Promise.all([page.waitForURL('**/app'),page.getByRole('button',{name:'Masuk',exact:true}).click()]);
}
(async()=>{
    const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || undefined,headless:true,args:['--no-sandbox']});
    const ownerContext = await browser.newContext({viewport:{width:1440,height:1000},colorScheme:'light'});
    const memberContext = await browser.newContext({viewport:{width:1440,height:1000},colorScheme:'light'});
    const owner = await ownerContext.newPage(); const member = await memberContext.newPage();
    for(const page of [owner,member]) {page.on('pageerror',error=>runtimeErrors.push(error.message));page.on('request',request=>network.push(request.url()));}
    // Capture every HTML form route without bearer values or real identity data.
    for(const [route,name] of [['/login','login'],['/register','register'],['/verify-email','verify'],['/verification/resend','resend'],['/password/forgot','forgot'],['/password/reset','reset'],['/invitations/accept','invite']]) {
        await owner.goto(BASE+route);await snapshot(owner,name);
    }
    record('foundation starts without a media permission request', !network.some(url=>/video_feed|webrtc|livekit/.test(url)));
    await registerAndVerify(owner,'phase1-owner@example.com','Dimas QA');
    record('registration, email confirmation and login complete', owner.url().endsWith('/app'));
    await snapshot(owner,'dashboard-empty');
    const cookies = await ownerContext.cookies();
    record('account session is HttpOnly and separated from legacy cookie',cookies.some(c=>c.name==='wewatch_platform'&&c.httpOnly&&c.sameSite==='Lax'));
    await owner.locator('#workspace-name').fill('Tim Operasional');
    await Promise.all([owner.waitForURL('**/workspaces/*'),owner.getByRole('button',{name:'Buat workspace',exact:true}).click()]);
    const workspaceId = owner.url().split('/').pop();
    record('workspace creator becomes Owner', await owner.getByText('Role Anda:').textContent().then(t=>t.includes('Owner')));
    await registerAndVerify(member,'phase1-viewer@example.com','Rani QA');
    const denied = await member.goto(BASE+'/workspaces/'+workspaceId);
    record('foreign workspace is not disclosed to an authenticated outsider',denied.status()===404);
    await snapshot(member,'error');
    await owner.locator('#invite-email').fill('phase1-viewer@example.com'); await owner.locator('#invite-role').selectOption('viewer');
    await Promise.all([owner.waitForURL('**/workspaces/'+workspaceId),owner.getByRole('button',{name:'Kirim undangan'}).click()]);
    const invite = mailboxToken('phase1-viewer@example.com');
    await member.goto(BASE+'/invitations/accept#token='+invite);await member.waitForFunction(()=>location.hash==='');
    await Promise.all([member.waitForURL('**/workspaces/'+workspaceId),member.getByRole('button',{name:'Konfirmasi bergabung'}).click()]);
    record('email-bound invitation grants Viewer only',await member.getByText('Role Anda:').textContent().then(t=>t.includes('Viewer')));
    record('viewer cannot see owner email or member management',await member.locator('#invite-email').count()===0 && !(await member.content()).includes('phase1-owner@example.com'));
    await snapshot(member,'workspace-viewer');
    const csrf = (await memberContext.request.get(BASE+'/api/session')).json();
    const forbidden = await memberContext.request.post(BASE+'/workspaces/'+workspaceId+'/settings', {data:{name:'Unauthorized'},headers:{'Content-Type':'application/json','X-CSRF-Token':(await csrf).csrf_token}});
    record('viewer write is denied server-side',forbidden.status()===403);
    await owner.reload();await snapshot(owner,'workspace-owner');
    await owner.goto(BASE+'/app');await snapshot(owner,'dashboard');
    await owner.setViewportSize({width:390,height:844});
    record('mobile workspace list has no overflow',await owner.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await snapshot(owner,'dashboard-mobile');
    await owner.goto(BASE+'/workspaces/'+workspaceId);await snapshot(owner,'workspace-mobile');
    record('mobile member management has no overflow',await owner.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await owner.setViewportSize({width:1440,height:1000});
    owner.on('dialog',dialog=>dialog.accept());
    await owner.locator('#owner-password').fill(PASSWORD);
    await Promise.all([owner.waitForURL('**/workspaces/'+workspaceId),owner.getByRole('button',{name:'Transfer ownership',exact:true}).click()]);
    record('ownership transfer demotes the prior Owner to Admin',await owner.getByText('Role Anda:').textContent().then(t=>t.includes('Admin')));
    await member.reload();record('new Owner is reflected on the next request',await member.getByText('Role Anda:').textContent().then(t=>t.includes('Owner')));
    await owner.goto(BASE+'/app');
    await Promise.all([owner.waitForURL('**/login'),owner.getByRole('button',{name:'Keluar dari semua sesi'}).click()]);
    record('logout-all returns to login and revokes session', (await ownerContext.request.get(BASE+'/api/me')).status()===401);
    await owner.goto(BASE+'/password/forgot');await owner.locator('#email').fill('phase1-owner@example.com');
    await Promise.all([owner.waitForURL('**/login'),owner.getByRole('button',{name:'Kirim email pemulihan'}).click()]);
    await owner.goto(BASE+'/password/reset#token='+mailboxToken('phase1-owner@example.com'));
    await owner.locator('#password').fill('phase-one-new-test-passphrase');
    await Promise.all([owner.waitForURL('**/login'),owner.getByRole('button',{name:'Simpan password baru'}).click()]);
    await owner.locator('#email').fill('phase1-owner@example.com');await owner.locator('#password').fill('phase-one-new-test-passphrase');
    await Promise.all([owner.waitForURL('**/app'),owner.getByRole('button',{name:'Masuk',exact:true}).click()]);
    record('password recovery works end to end',owner.url().endsWith('/app'));
    record('no third-party assets or requests in account workflow',network.every(url=>url.startsWith(BASE)));
    record('no bearer token appears in an HTTP request',network.every(url=>!url.includes('token=')));
    await owner.setViewportSize({width:390,height:844});await owner.goto(BASE+'/register');await snapshot(owner,'register-mobile');
    record('mobile registration has no horizontal overflow',await owner.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const summary={results,runtimeErrors,scope:'Real account/session/SQLite/file-mail paths on loopback; no real SMTP, camera, Windows, or meeting provider'};
    fs.writeFileSync(path.join(OUTPUT,'platform-browser-results.json'),JSON.stringify(summary,null,2));
    console.log(JSON.stringify(summary));await browser.close();
    process.exit(results.some(result=>!result.pass)||runtimeErrors.length?1:0);
})().catch(error=>{console.error(error.message);process.exit(1);});
