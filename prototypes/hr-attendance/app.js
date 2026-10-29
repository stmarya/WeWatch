'use strict';

const state = { data: null, events: [], cameraStream: null };
const $ = (id) => document.getElementById(id);

function setMessage(message, isError = false) {
  const node = $('sensorMessage');
  node.textContent = message;
  node.classList.toggle('error', isError);
}

function safeText(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

function formatTime(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta' }).format(new Date(iso));
}

function renderSeedData() {
  const { employees, schedules, attendanceRecords, correctionRequests } = state.data;
  $('employeeCount').textContent = employees.length;
  $('recordCount').textContent = attendanceRecords.length;
  $('pendingCount').textContent = correctionRequests.filter((item) => item.status === 'pending').length;

  const select = $('employeeSelect');
  select.innerHTML = employees.map((employee) =>
    `<option value="${safeText(employee.employeeId)}">${safeText(employee.displayName)} · ${safeText(employee.employeeId)}</option>`
  ).join('');
  select.disabled = false;

  const scheduleById = Object.fromEntries(schedules.map((schedule) => [schedule.scheduleId, schedule]));
  const employee = employees[0];
  const schedule = scheduleById[employee.scheduleId];
  $('scheduleInfo').textContent = `${employee.team} · ${employee.workMode} · ${schedule.label} · ${schedule.start}–${schedule.end} (${schedule.timezone})`;
  select.addEventListener('change', () => {
    const selected = employees.find((item) => item.employeeId === select.value);
    const assigned = scheduleById[selected.scheduleId];
    $('scheduleInfo').textContent = `${selected.team} · ${selected.workMode} · ${assigned.label} · ${assigned.start}–${assigned.end} (${assigned.timezone})`;
  });

  $('scheduleList').innerHTML = schedules.map((item) =>
    `<li><strong>${safeText(item.label)}</strong>: ${safeText(item.start)}–${safeText(item.end)} · ${safeText(item.days.join(', '))} <span class="subtle">(contoh, bukan kebijakan)</span></li>`
  ).join('');

  $('recordsBody').innerHTML = attendanceRecords.map((record) => {
    const verify = [record.gpsVerification?.status, record.cameraVerification?.status]
      .filter((value) => value && value !== 'not_used')
      .join(' / ') || 'manual';
    return `<tr><td>${safeText(record.date)}</td><td>${safeText(record.employeeId)}</td><td>${safeText(scheduleById[record.scheduleId]?.label ?? record.scheduleId)}</td><td>${safeText(formatTime(record.checkIn))}</td><td>${safeText(formatTime(record.checkOut))}</td><td>${safeText(record.status)}</td><td>${safeText(verify)}</td></tr>`;
  }).join('');
  $('recordsNotice').textContent = 'Seluruh record seed bersifat fiktif.';
  $('checkInButton').disabled = false;
  $('checkOutButton').disabled = false;
  setMessage('Siap. Pilih profil contoh; sensor tetap tidak aktif sampai Anda memulai tindakan.');
}

function requestOneTimeLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('Browser ini tidak menyediakan geolocation. Check-in manual tetap dapat digunakan.'));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracyMeters: position.coords.accuracy,
        capturedAt: new Date(position.timestamp).toISOString(),
        storedOnServer: false,
      }),
      (error) => reject(new Error(error.message || 'Izin lokasi tidak diberikan. Check-in manual tetap dapat digunakan.')),
      { enableHighAccuracy: false, maximumAge: 0, timeout: 10000 },
    );
  });
}

async function startCamera() {
  if (!$('cameraOptIn').checked) throw new Error('Aktifkan pilihan kamera terlebih dahulu.');
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('Kamera tidak tersedia; gunakan check-in manual.');
  if (state.cameraStream) return;
  state.cameraStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
  $('cameraPreview').srcObject = state.cameraStream;
  $('cameraBox').hidden = false;
  $('stopCamera').disabled = false;
  $('cameraStatus').textContent = 'Preview lokal aktif; tekan “Matikan kamera” kapan saja.';
}

function stopCamera() {
  if (state.cameraStream) {
    state.cameraStream.getTracks().forEach((track) => track.stop());
    state.cameraStream = null;
  }
  $('cameraPreview').srcObject = null;
  $('cameraBox').hidden = true;
  $('stopCamera').disabled = true;
  $('cameraStatus').textContent = 'Kamera mati. Tidak ada frame yang disimpan.';
}

function runTransientCameraCheck() {
  if (!$('cameraOptIn').checked) return { status: 'not_used', imageStored: false, faceRecognition: false };
  const liveVideoTracks = state.cameraStream?.getVideoTracks?.()
    .filter((track) => track.readyState === 'live') ?? [];
  if (!liveVideoTracks.length) {
    throw new Error('Aktifkan preview kamera dan beri izin terlebih dahulu; check-in manual tetap tersedia.');
  }
  // Confirm the user-enabled camera stream, then stop it. No frame is captured or stored.
  stopCamera();
  return { status: 'preview_tested_and_stopped', imageStored: false, faceRecognition: false };
}

function renderSessionEvents() {
  const container = $('sessionEvents');
  if (!state.events.length) {
    container.innerHTML = '<p class="subtle">Belum ada aksi.</p>';
    $('locationOutput').hidden = true;
    return;
  }
  container.innerHTML = state.events.map((event) => {
    const when = new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(event.timestamp));
    const sensorText = [event.gps ? 'GPS satu kali' : null, event.camera.status !== 'not_used' ? 'kamera smoke-test' : null].filter(Boolean).join(' · ') || 'manual';
    return `<div class="event-row"><strong>${safeText(event.eventType)} · ${safeText(event.employeeId)}</strong><span class="event-meta">${safeText(when)} · ${safeText(sensorText)} · hanya di memori sesi</span></div>`;
  }).join('');
  const lastLocation = state.events.find((event) => event.gps)?.gps;
  if (lastLocation) {
    $('locationOutput').hidden = false;
    $('locationOutput').textContent = `Koordinat GPS sesi ini: ${lastLocation.latitude.toFixed(5)}, ${lastLocation.longitude.toFixed(5)} · akurasi ±${Math.round(lastLocation.accuracyMeters)} m. Tidak dikirim ke server; tutup halaman untuk menghapus.`;
  } else {
    $('locationOutput').hidden = true;
  }
}

async function recordAttendance(eventType) {
  const employeeId = $('employeeSelect').value;
  const button = eventType === 'check_in' ? $('checkInButton') : $('checkOutButton');
  button.disabled = true;
  setMessage('Memproses tindakan yang Anda mulai…');
  let gps = null;
  let camera = { status: 'not_used', imageStored: false, faceRecognition: false };
  try {
    if ($('gpsOptIn').checked) {
      try {
        gps = await requestOneTimeLocation();
      } catch (error) {
        setMessage(`${error.message} Tindakan tetap dapat dicatat secara manual.`, true);
      }
    }
    if ($('cameraOptIn').checked) {
      try {
        camera = runTransientCameraCheck();
      } catch (error) {
        camera = { status: 'unavailable_or_denied', imageStored: false, faceRecognition: false };
        setMessage(`${error.message} Tindakan tetap dapat dicatat secara manual.`, true);
      }
    }
    state.events.unshift({
      employeeId,
      eventType,
      timestamp: new Date().toISOString(),
      source: 'employee_initiated_demo',
      gps,
      camera,
    });
    renderSessionEvents();
    if (gps || camera.status === 'stream_tested_frame_discarded') {
      setMessage('Tindakan demo dicatat hanya di memori halaman. Data seed dan sensor tidak dikirim ke server.');
    } else {
      setMessage('Tindakan demo dicatat secara manual hanya di memori halaman.');
    }
  } finally {
    button.disabled = false;
  }
}

$('checkInButton').addEventListener('click', () => recordAttendance('check_in'));
$('checkOutButton').addEventListener('click', () => recordAttendance('check_out'));
$('startCamera').addEventListener('click', async () => {
  try {
    await startCamera();
    setMessage('Preview kamera aktif lokal. Matikan kapan saja; frame tidak disimpan.');
  } catch (error) {
    setMessage(`${error.message} Check-in manual tetap tersedia.`, true);
  }
});
$('stopCamera').addEventListener('click', stopCamera);
$('clearSession').addEventListener('click', () => {
  state.events = [];
  stopCamera();
  renderSessionEvents();
  setMessage('Aksi sesi dihapus dari memori halaman.');
});
$('cameraOptIn').addEventListener('change', () => {
  $('startCamera').disabled = !$('cameraOptIn').checked;
  if (!$('cameraOptIn').checked) stopCamera();
});
window.addEventListener('pagehide', stopCamera);

fetch('./sample_data.json', { cache: 'no-store' })
  .then((response) => {
    if (!response.ok) throw new Error('File data contoh tidak dapat dimuat.');
    return response.json();
  })
  .then((data) => { state.data = data; renderSeedData(); })
  .catch((error) => setMessage(`${error.message} Jalankan prototipe melalui localhost; jangan buka sebagai file://.`, true));
