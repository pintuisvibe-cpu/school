// Dependency-free browser smoke tests: simulated DOM, face model, QR camera, fetch.
// Run with: node tests/frontend_smoke.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function scriptFrom(page) {
  const html = fs.readFileSync(path.join(__dirname, '..', page), 'utf8');
  const inline = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
  assert(inline.length > 0, `${page} must have an inline script`);
  return inline.at(-1)[1];
}

function createBrowser(page, authRequired = true) {
  const elements = new Map(), calls = [], timers = [], tokens = new Map();
  const downloads = [], blobs = [];
  let scanner = null, forceUnauthorized = false, attendanceRows = [];
  function el(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id, value: '', files: [], textContent: '', innerHTML: '', className: '',
        style: {}, open: false, disabled: false, readyState: 3, handlers: {},
        classList: {add() {}, remove() {}},
        addEventListener(type, handler) {this.handlers[type] = handler;},
        querySelector() {return null;}, reset() {},
      });
    }
    return elements.get(id);
  }
  const document = {
    getElementById: el,
    querySelector(selector) {return selector === '#qr-reader video' ? el('cameraVideo') : null;},
    createElement() {return {href: '', download: '', click() {downloads.push(this.download);}, remove() {}};},
    body: {appendChild() {}},
  };
  const sessionStorage = {
    getItem(key) {return tokens.get(key) ?? null;},
    setItem(key, value) {tokens.set(key, String(value));},
    removeItem(key) {tokens.delete(key);},
  };
  const faceapi = {
    nets: Object.fromEntries(['tinyFaceDetector', 'faceLandmark68Net', 'faceRecognitionNet']
      .map(name => [name, {loadFromUri: async () => {}}])),
    TinyFaceDetectorOptions: class {},
    detectAllFaces() {
      return {withFaceLandmarks() {
        return {withFaceDescriptors: async () => [{descriptor: Array(128).fill(0.1)}]};
      }};
    },
  };
  function response(status, body) {
    return {ok: status >= 200 && status < 300, status, json: async () => body};
  }
  const fetch = async (url, options = {}) => {
    calls.push({url, options});
    if (url.endsWith('/health')) return response(200, {storage: 'sqlite', auth_required: authRequired});
    const token = options.headers?.Authorization;
    if ((authRequired && token !== 'Bearer test-token') || forceUnauthorized) {
      return response(401, {detail: 'Unauthorized'});
    }
    if (url.endsWith('/api/attendance')) return response(200, attendanceRows);
    if (url.endsWith('/api/register')) return response(200, {
      status: 'success', student_id: 'S1', student_name: 'Student', card_token: 'opaque-card',
    });
    if (url.endsWith('/api/enroll-face')) return response(200, {status: 'success', student_id: 'S1'});
    if (url.endsWith('/api/verify-attendance')) return response(200, {
      status: 'success', student_name: 'Student', time: '15:30:00',
    });
    throw new Error(`Unexpected fetch: ${url}`);
  };
  class FakeScanner {
    constructor() {this.pauseArgs = []; this.resumes = 0; scanner = this;}
    async start(camera, config, callback) {this.callback = callback; this.isScanning = true;}
    pause(value) {this.pauseArgs.push(value);}
    resume() {this.resumes++;}
  }
  class FakeImage {
    set src(value) {queueMicrotask(() => this.onload?.());}
  }
  const qrCards = [];
  function QRCode(node, options) {qrCards.push(options.text);}
  QRCode.CorrectLevel = {H: 1};
  const ctx = vm.createContext({
    document, sessionStorage, fetch, faceapi, QRCode, Image: FakeImage,
    Html5Qrcode: FakeScanner, Html5QrcodeSupportedFormats: {QR_CODE: 1},
    navigator: {mediaDevices: {getUserMedia: async () => {}}},
    window: {isSecureContext: true},
    URL: {createObjectURL: blob => {if(blob?.parts)blobs.push(blob);return 'blob:fake';}, revokeObjectURL() {}},
    Blob: class {constructor(parts, options) {this.parts = parts; this.options = options;}},
    Intl, console,
    setTimeout(fn) {timers.push(fn); return timers.length;}, clearTimeout() {},
  });
  vm.runInContext(scriptFrom(page), ctx, {filename: page});
  return {el, calls, tokens, qrCards, timers, ctx, downloads, blobs,
    scanner: () => scanner, forceUnauthorized(value) {forceUnauthorized = value;},
    setAttendance(rows) {attendanceRows = rows;}};
}

const settle = () => new Promise(resolve => setImmediate(resolve));

async function run() {
  const admin = createBrowser('admin.html');
  await settle();
  assert.equal(admin.el('authSettings').open, true, 'admin should request a missing API token');
  assert.equal(admin.calls.find(c => c.url.endsWith('/api/attendance')).options.headers.Authorization,
    undefined, 'admin must not fabricate a token');
  admin.el('authInput').value = 'test-token';
  admin.el('authForm').handlers.submit({preventDefault() {}});
  await settle();
  assert.equal(admin.tokens.get('attendance_api_token'), 'test-token');
  assert.equal(admin.calls.filter(c => c.url.endsWith('/api/attendance')).at(-1)
    .options.headers.Authorization, 'Bearer test-token');
  assert.equal(admin.el('authInput').value, '', 'do not leave the token in the form');
  assert.equal(admin.el('csvBtn').disabled, false);
  admin.setAttendance([{student_id: '=SUM(1,2)', name: '+cmd', date: '2026-11-12',
    time: '15:30:00', status: 'Present'}]);
  await vm.runInContext('loadAttendance()', admin.ctx);
  admin.el('csvBtn').handlers.click();
  const csv = admin.blobs.at(-1).parts[0];
  assert(csv.startsWith('\uFEFF'));
  assert(csv.includes(`"'=SUM(1,2)"`), 'student ID formula should be escaped');
  assert(csv.includes(`"'+cmd"`), 'name formula should be escaped');
  assert.match(admin.downloads.at(-1), /^attendance-\d{4}-\d{2}-\d{2}\.csv$/);
  vm.runInContext('capturedCanvas = {}', admin.ctx);
  const registerForm = admin.el('registerForm');
  const fields = {student_id: {value: 'S1'}, name: {value: 'Student'}, class_name: {value: '5'}};
  registerForm.name = 'native form name property'; // Don't rely on form.name being the input.
  registerForm.elements = {namedItem: name => fields[name]};
  await registerForm.handlers.submit({preventDefault() {}, currentTarget: registerForm});
  const registration = admin.calls.find(c => c.url.endsWith('/api/register'));
  assert.equal(registration.options.headers.Authorization, 'Bearer test-token');
  assert.equal(JSON.parse(registration.options.body).name, 'Student');
  assert.deepEqual(admin.qrCards, ['opaque-card']);
  const enrollForm = admin.el('enrollForm');
  enrollForm.elements = {namedItem: name => ({student_id: {value: 'S1'}})[name]};
  admin.el('enrollPhoto').files = [{name: 'face.jpg'}];
  await enrollForm.handlers.submit({preventDefault() {}, currentTarget: enrollForm});
  assert.equal(admin.calls.find(c => c.url.endsWith('/api/enroll-face')).options.headers.Authorization,
    'Bearer test-token');
  admin.el('clearAuth').handlers.click();
  assert.equal(admin.tokens.has('attendance_api_token'), false);

  const gate = createBrowser('scanner.html');
  await settle();
  assert.equal(gate.el('tokenSettings').open, true, 'scanner should prompt before scanning');
  assert(gate.scanner()?.callback, 'scanner should start and install a QR callback');
  gate.el('tokenInput').value = 'test-token';
  gate.el('tokenForm').handlers.submit({preventDefault() {}});
  assert.equal(gate.el('tokenSettings').open, false);
  await gate.scanner().callback('opaque-card');
  const verify = gate.calls.find(c => c.url.endsWith('/api/verify-attendance'));
  assert.equal(verify.options.headers.Authorization, 'Bearer test-token');
  assert.equal(JSON.parse(verify.options.body).student_id, 'opaque-card');
  assert.deepEqual(gate.scanner().pauseArgs, [false], 'QR must pause without pausing video');
  assert.equal(gate.el('resultTitle').textContent, 'Present: Student');
  gate.timers.at(-1)(); // Reset for the next scan.
  gate.forceUnauthorized(true);
  await gate.scanner().callback('opaque-card');
  assert.equal(gate.el('tokenSettings').open, true, 'scanner should reopen token form on 401');

  const openAdmin = createBrowser('admin.html', false);
  await settle();
  assert.equal(openAdmin.el('authSettings').open, false);
  assert.equal(openAdmin.calls.find(c => c.url.endsWith('/api/attendance'))
    .options.headers.Authorization, undefined);
  console.log('Frontend smoke tests passed (admin, scanner, token and QR camera).');
}
run().catch(error => {console.error(error); process.exitCode = 1;});
