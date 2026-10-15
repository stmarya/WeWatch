'use strict';
/* Local browser preview only. No recording, cloud calls, remote controls or model inference. */
class PreviewController {
    constructor(adapters) {
        this.a = adapters;
        this.kinds = ['camera', 'microphone'];
        this.state = Object.fromEntries(this.kinds.map(kind => [kind, {epoch:0, stream:null, pending:false, authorized:false, deadline:null, timer:null, acquisition:null}]));
    }
    emit() { this.a.changed(this.state); }
    stop(kind, reason='Dihentikan', revoke=true) {
        const state = this.state[kind];
        state.epoch++; state.pending = false; state.authorized = false; state.deadline = null;
        this.a.clearTimer(state.timer); this.a.clearTimer(state.acquisition);
        state.timer = null; state.acquisition = null;
        if (state.stream) state.stream.getTracks().forEach(track => track.stop());
        state.stream = null;
        this.a.detach(kind); this.emit();
        if (revoke) Promise.resolve(this.a.revoke(kind)).catch(() => this.a.message('Preview lokal sudah berhenti; pencabutan di server belum terkonfirmasi. Izin server tetap berakhir maksimal 10 menit.'));
        this.a.message(reason);
    }
    stopAll(reason='Semua preview dihentikan', revoke=true) { this.kinds.forEach(kind => this.stop(kind, reason, revoke)); }
    async start(kind) {
        const state = this.state[kind];
        if (state.pending || state.stream) return;
        const epoch = ++state.epoch; state.pending = true; state.authorized = false; this.emit();
        const started = this.a.now();
        try {
            const grant = await this.a.grant(kind);
            if (state.epoch !== epoch || !this.a.visible()) { await this.a.revoke(kind); return; }
            state.authorized = true;
            const remaining = Math.min(600000, (grant.expires_at - grant.server_time) * 1000) - (this.a.now() - started);
            if (!Number.isFinite(remaining) || remaining <= 0) throw new Error('Izin sudah kedaluwarsa.');
            state.deadline = this.a.now() + remaining;
            state.timer = this.a.timer(() => this.stop(kind, 'Izin kedaluwarsa. Aktifkan kembali secara manual.'), remaining);
            state.acquisition = this.a.timer(() => this.stop(kind, 'Permintaan media melewati batas waktu. Coba lagi secara manual.'), Math.min(60000, remaining));
            const stream = await this.a.media(kind);
            if (state.epoch !== epoch || !this.a.visible()) { stream.getTracks().forEach(track => track.stop()); return; }
            this.a.clearTimer(state.acquisition); state.acquisition = null;
            const tracks = kind === 'camera' ? stream.getVideoTracks() : stream.getAudioTracks();
            if (!tracks.length || tracks.every(track => track.readyState === 'ended')) {
                stream.getTracks().forEach(track => track.stop());
                throw new Error('Track media tidak tersedia.');
            }
            state.stream = stream; state.pending = false;
            tracks.forEach(track => track.addEventListener('ended', () => this.stop(kind, 'Izin media dicabut atau perangkat terputus.')));
            this.a.attach(kind, stream); this.a.report(kind, 'available'); this.emit();
            this.a.message(kind === 'camera' ? 'Kamera aktif lokal, tanpa upload atau rekaman.' : 'Track mikrofon aktif lokal; suara tidak diputar atau disimpan.');
        } catch (error) {
            if (state.epoch !== epoch) return;
            const status = ['NotAllowedError','SecurityError'].includes(error.name) ? 'denied' : 'unavailable';
            this.a.report(kind, status);
            this.stop(kind, status === 'denied' ? 'Izin ditolak. Periksa izin situs/browser lalu coba manual.' : 'Preview tidak dapat dimulai. Periksa koneksi/perangkat lalu coba manual.');
        }
    }
    reconcile(grants) {
        for (const kind of this.kinds) {
            const state = this.state[kind];
            // Reconcile both an authorized permission prompt and attached tracks, never an unacknowledged grant request.
            if (state.authorized && (state.stream || state.pending) && !grants.some(grant => grant.capability === kind + '_preview')) this.stop(kind, 'Izin server tidak aktif. Preview dihentikan.');
        }
    }
}
if (typeof module !== 'undefined' && module.exports) module.exports = {PreviewController};

if (typeof document !== 'undefined') {
    async function requestJSON(url, value, csrf) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 3000);
        try {
            const options = {signal:controller.signal, credentials:'same-origin', cache:'no-store', headers:{'Accept':'application/json'}};
            if (value !== undefined) {
                options.method = 'POST'; options.headers['Content-Type'] = 'application/json';
                options.headers['X-CSRF-Token'] = csrf; options.body = JSON.stringify(value);
            }
            const response = await fetch(url, options);
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Permintaan tidak berhasil.');
            return result;
        } finally { clearTimeout(timeout); }
    }
    const root = document.getElementById('onboarding');
    if (root) {
        const workspace = encodeURIComponent(root.dataset.workspace), csrf = root.dataset.csrf;
        let device = root.dataset.device;
        let pairingID = null;
        let isVisible = !document.hidden;
        let suspended = false;
        let checking = false;
        const statusURL = `/api/workspaces/${workspace}/onboarding`;
        const base = () => `/workspaces/${workspace}/devices/${encodeURIComponent(device)}`;
        const messageNode = document.getElementById('onboarding-message');
        const message = text => { messageNode.textContent = text; messageNode.hidden = false; };
        const report = {secure_context: window.isSecureContext, media_supported: !!navigator.mediaDevices?.getUserMedia, camera:'unknown', microphone:'unknown'};
        const saveReport = async () => {
            if (device) await requestJSON(base()+'/readiness', report, csrf);
        };
        const updateReadiness = () => {
            document.getElementById('check-secure').textContent = report.secure_context ? 'Tersedia' : 'Tidak aman · gunakan HTTPS';
            document.getElementById('check-media').textContent = report.media_supported ? 'Didukung' : 'Tidak didukung';
            const names = {unknown:'Belum diminta', available:'Uji berhasil (laporan browser)', denied:'Izin ditolak', unavailable:'Tidak tersedia'};
            for (const kind of ['camera','microphone']) document.getElementById('check-'+kind).textContent = names[report[kind]];
        };
        const preview = new PreviewController({
            now:()=>performance.now(), timer:(fn,ms)=>setTimeout(fn,ms), clearTimer:id=>clearTimeout(id),
            visible:()=>isVisible && navigator.onLine && !suspended,
            grant:async kind => {
                if (!device || !isVisible || !navigator.onLine || !report.secure_context || !report.media_supported) throw new Error('Browser belum siap.');
                const response = await requestJSON(base()+'/consents', {capability:kind+'_preview', policy_version:root.dataset.policy, acknowledged:true}, csrf);
                return response.grant;
            },
            revoke:async kind => { if (device) await requestJSON(base()+'/consents/revoke', {capability:kind+'_preview'}, csrf); },
            media:kind=>navigator.mediaDevices.getUserMedia(kind === 'camera' ? {video:true,audio:false} : {video:false,audio:true}),
            attach:(kind,stream)=>{ if(kind==='camera'){const video=document.getElementById('local-preview');video.srcObject=stream;video.hidden=false;document.getElementById('preview-empty').hidden=true;} },
            detach:kind=>{ if(kind==='camera'){const video=document.getElementById('local-preview');video.srcObject=null;video.hidden=true;document.getElementById('preview-empty').hidden=false;} },
            report:(kind,status)=>{ report[kind]=status;updateReadiness();saveReport().catch(()=>preview.stopAll('Koneksi diagnostik gagal. Preview dihentikan.')); },
            changed:states=>{
                for (const kind of ['camera','microphone']) {
                    const state=states[kind];
                    document.getElementById(kind+'-start').disabled=!device || state.pending || !!state.stream || !isVisible || suspended;
                    document.getElementById(kind+'-stop').disabled=!state.pending && !state.stream;
                    const seconds=Math.max(0,Math.ceil(((state.deadline||0)-performance.now())/1000));
                    const remaining=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
                    document.getElementById(kind+'-state').textContent=state.stream?`AKTIF LOKAL · sisa ${remaining}`:state.pending?'Menunggu izin browser…':'Tidak aktif · tanpa izin otomatis';
                }
            },message,
        });
        updateReadiness();
        for (const kind of ['camera','microphone']) {
            document.getElementById(kind+'-start').addEventListener('click',()=>{suspended=false;preview.start(kind);});
            document.getElementById(kind+'-stop').addEventListener('click',()=>preview.stop(kind));
        }
        document.getElementById('emergency-stop').addEventListener('click',()=>preview.stopAll('STOP: semua track lokal dihentikan; pencabutan izin diminta.'));
        document.getElementById('check-readiness').addEventListener('click',()=>{
            updateReadiness();saveReport().then(()=>message('Pemeriksaan selesai tanpa membuka kamera/mikrofon.')).catch(()=>{preview.stopAll('Pemeriksaan gagal; tidak ada izin baru yang diberikan.');});
        });
        const beaconRevoke = () => {
            if (!device) return;
            const form = new FormData(); form.set('csrf_token', csrf);
            navigator.sendBeacon(base()+'/consents/revoke', form);
        };
        const hide = () => {isVisible=false;suspended=true;preview.stopAll('Tab tidak terlihat. Semua preview dihentikan.');beaconRevoke();};
        document.addEventListener('visibilitychange',()=>{if(document.hidden)hide();else{isVisible=true;suspended=false;preview.emit();}});
        window.addEventListener('pagehide',hide);
        window.addEventListener('pageshow',()=>{isVisible=!document.hidden;suspended=false;preview.emit();});
        window.addEventListener('offline',()=>preview.stopAll('Koneksi offline. Tidak ada preview yang dimulai ulang otomatis.'));
        document.querySelectorAll('[data-device-revoke]').forEach(form=>form.addEventListener('submit',()=>{if(form.dataset.deviceRevoke===device)preview.stopAll('Pairing dicabut.');}));
        async function checkStatus() {
            if (checking || !isVisible) return;
            checking=true;
            try {
                const status=await requestJSON(statusURL);
                if (device && (!status.device || status.device.id!==device)) {
                    preview.stopAll('Pairing/sesi dicabut. Pairing ulang diperlukan.');device='';suspended=true;preview.emit();
                    document.getElementById('pair-status').textContent='Tidak aktif · muat ulang untuk pairing';
                } else if (!device && status.device) {
                    message('Pairing selesai. Muat ulang halaman untuk melanjutkan preview.');
                    document.getElementById('pair-status').textContent='Terpasang · muat ulang';
                } else preview.reconcile(status.grants);
            } catch (_) { preview.stopAll('Verifikasi koneksi/izin gagal. Preview dihentikan.'); }
            finally {checking=false;}
        }
        setInterval(checkStatus,4000);
        setInterval(()=>{
            for(const kind of ['camera','microphone']) {
                const state=preview.state[kind];
                if(state.deadline!==null && performance.now()>=state.deadline) preview.stop(kind,'Izin kedaluwarsa.');
            }
            preview.emit();
        },1000);
        // Never resume media on page load, even if a previous server grant remains unexpired.
        if (device) requestJSON(base()+'/consents/revoke', {}, csrf).catch(()=>message('Pencabutan izin lama belum terkonfirmasi; preview tetap tidak aktif.'));
        document.getElementById('pair-form')?.addEventListener('submit',async event=>{
            event.preventDefault(); const button=document.getElementById('pair-request');button.disabled=true;
            try {
                const result=await requestJSON(`/workspaces/${workspace}/pairing`,{name:document.getElementById('browser-name').value},csrf);
                pairingID=result.pairing.id;
                document.getElementById('pair-token').value=result.pairing.token;
                document.getElementById('pair-link').href='/device-pairing#token='+encodeURIComponent(result.pairing.token);
                document.getElementById('pair-result').hidden=false;
                message('Token dibuat. Tinjau dan konfirmasi sebelum batas 5 menit.');
            } catch(error){message(error.message);}
            finally{button.disabled=false;}
        });
        document.getElementById('pair-cancel')?.addEventListener('click',async()=>{
            try {
                await requestJSON(`/workspaces/${workspace}/pairing/${encodeURIComponent(pairingID)}/cancel`,{},csrf);
                document.getElementById('pair-result').hidden=true;document.getElementById('pair-token').value='';document.getElementById('pair-link').href='/device-pairing';pairingID=null;
                message('Token dibatalkan.');
            } catch(error){message(error.message);}
        });
    }
    const approval=document.getElementById('pairing-approval');
    if(approval){
        const field=document.getElementById('approval-token'), details=document.getElementById('pair-approval-details');
        const msg=text=>{const node=document.getElementById('approval-message');node.hidden=false;node.textContent=text;};
        let reviewedToken=null;
        field.addEventListener('input',()=>{reviewedToken=null;details.hidden=true;});
        document.getElementById('pair-inspect-form').addEventListener('submit',async event=>{
            event.preventDefault();details.hidden=true;reviewedToken=null;
            try{
                const token=field.value;
                const result=await requestJSON('/device-pairing/inspect',{token},approval.dataset.csrf);
                if(field.value!==token)return;
                reviewedToken=token;
                document.getElementById('approval-name').textContent=result.pairing.name;
                document.getElementById('approval-workspace').textContent='Workspace: '+result.pairing.workspace_name;
                details.hidden=false;
            }catch(error){msg(error.message);}
        });
        document.getElementById('pair-approve').addEventListener('click',async event=>{
            if(!reviewedToken || field.value!==reviewedToken)return;
            const button=event.currentTarget;button.disabled=true;
            try{
                const result=await requestJSON('/device-pairing/approve',{token:reviewedToken,acknowledged:true},approval.dataset.csrf);
                reviewedToken=null;field.value='';details.hidden=true;msg(result.message);
                const link=document.getElementById('approval-return');link.href='/workspaces/'+encodeURIComponent(result.workspace_id)+'/onboarding';link.textContent='Kembali ke browser onboarding';
            }catch(error){msg(error.message);button.disabled=false;}
        });
    }
}
