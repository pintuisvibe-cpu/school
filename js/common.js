/* Shared helpers: Supabase RPC client, QR generation, face engine, UI utils. */
(function () {
  const cfg = window.SCHOOL_CONFIG || {};
  const BASE = (cfg.supabaseUrl || "").replace(/\/$/, "");

  /* ------------------------------------------------------------------ */
  /* Supabase RPC                                                        */
  /* ------------------------------------------------------------------ */
  async function rpc(fn, args = {}) {
    if (!BASE) throw new Error("Supabase URL কনফিগার করা নেই।");
    let res;
    try {
      res = await fetch(`${BASE}/rest/v1/rpc/${fn}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          apikey: cfg.supabaseKey,
          Authorization: `Bearer ${cfg.supabaseKey}`,
        },
        body: JSON.stringify(args),
      });
    } catch (e) {
      throw new Error("সার্ভারে পৌঁছানো যাচ্ছে না। ইন্টারনেট সংযোগ পরীক্ষা করুন।");
    }
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (e) {
      data = null;
    }
    if (!res.ok) {
      const msg =
        (data && (data.message || data.hint || data.detail || data.error)) ||
        `সার্ভার ত্রুটি (${res.status})`;
      throw new Error(msg);
    }
    return data;
  }

  /* ------------------------------------------------------------------ */
  /* Session (admin PIN kept in sessionStorage only)                     */
  /* ------------------------------------------------------------------ */
  const KEY_PIN = "school.admin.pin";
  const sess = {
    get pin() {
      return sessionStorage.getItem(KEY_PIN) || "";
    },
    set pin(v) {
      if (v) sessionStorage.setItem(KEY_PIN, v);
      else sessionStorage.removeItem(KEY_PIN);
    },
  };

  /* ------------------------------------------------------------------ */
  /* QR code (real, standards-compliant, generated locally)              */
  /* ------------------------------------------------------------------ */
  function buildQr(text) {
    if (typeof qrcode !== "function") throw new Error("QR লাইব্রেরি লোড হয়নি।");
    // Type 0 = auto size, level H keeps the code readable after print wear.
    const qr = qrcode(0, "H");
    qr.addData(String(text), "Byte");
    qr.make();
    return qr;
  }

  function qrSvg(text, size = 220, dark = "#0f172a", light = "#ffffff") {
    const qr = buildQr(text);
    const n = qr.getModuleCount();
    const quiet = 2;
    const total = n + quiet * 2;
    let path = "";
    // Merge horizontal runs so the path stays small and prints crisply.
    for (let r = 0; r < n; r++) {
      let c = 0;
      while (c < n) {
        if (!qr.isDark(r, c)) {
          c++;
          continue;
        }
        let start = c;
        while (c < n && qr.isDark(r, c)) c++;
        path += `M${start + quiet} ${r + quiet}h${c - start}v1h${-(c - start)}z`;
      }
    }
    return (
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} ${total}" ` +
      `width="${size}" height="${size}" shape-rendering="crispEdges" role="img" aria-label="QR">` +
      `<rect width="${total}" height="${total}" fill="${light}"/>` +
      `<path d="${path}" fill="${dark}"/></svg>`
    );
  }

  function qrDataUrl(text, cellSize = 12, margin = 24) {
    return buildQr(text).createDataURL(cellSize, margin);
  }

  /** Canvas with the QR at an exact pixel size (used for PNG/print exports). */
  function qrCanvas(text, px = 640, dark = "#0f172a", light = "#ffffff") {
    const qr = buildQr(text);
    const n = qr.getModuleCount();
    const quiet = 4;
    const cell = Math.max(1, Math.floor(px / (n + quiet * 2)));
    const size = cell * (n + quiet * 2);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = light;
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = dark;
    for (let r = 0; r < n; r++)
      for (let c = 0; c < n; c++)
        if (qr.isDark(r, c)) ctx.fillRect((c + quiet) * cell, (r + quiet) * cell, cell, cell);
    return canvas;
  }

  /* ------------------------------------------------------------------ */
  /* Face engine (browser-local, no images uploaded)                     */
  /* ------------------------------------------------------------------ */
  const MODEL_URL = "/static/models";
  let modelsPromise = null;

  function faceAvailable() {
    return typeof faceapi !== "undefined";
  }

  async function loadModels() {
    if (!faceAvailable()) throw new Error("Face library লোড হয়নি। ইন্টারনেট সংযোগ দেখুন।");
    if (!modelsPromise) {
      modelsPromise = Promise.all([
        faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
        faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL),
        faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
      ]).catch((err) => {
        modelsPromise = null;
        throw err;
      });
    }
    await modelsPromise;
  }

  const detectorOptions = () =>
    new faceapi.TinyFaceDetectorOptions({ inputSize: 416, scoreThreshold: 0.4 });

  async function descriptorFrom(input) {
    await loadModels();
    const faces = await faceapi
      .detectAllFaces(input, detectorOptions())
      .withFaceLandmarks()
      .withFaceDescriptors();
    if (faces.length === 0)
      throw new Error("ছবিতে মুখ শনাক্ত হয়নি। আলো ঠিক করে আবার চেষ্টা করুন।");
    if (faces.length > 1) throw new Error("ছবিতে একাধিক মুখ আছে; শুধু একজনের ছবি দিন।");
    return Array.from(faces[0].descriptor);
  }

  function distance(a, b) {
    if (!a || !b || a.length !== b.length) return Infinity;
    let sum = 0;
    for (let i = 0; i < a.length; i++) sum += (a[i] - b[i]) ** 2;
    return Math.sqrt(sum);
  }

  /* ------------------------------------------------------------------ */
  /* Camera helper                                                       */
  /* ------------------------------------------------------------------ */
  async function startCamera(video, { facing = "user" } = {}) {
    if (!window.isSecureContext)
      throw new Error("ক্যামেরার জন্য HTTPS লিংক দরকার (localhost-এও চলে)।");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
      throw new Error("এই ব্রাউজারে ক্যামেরা সাপোর্ট নেই। Chrome বা Safari ব্যবহার করুন।");
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    video.srcObject = stream;
    video.setAttribute("playsinline", "true");
    await video.play().catch(() => {});
    return stream;
  }

  function cameraErrorMessage(e) {
    const t = `${e?.name || ""} ${e?.message ?? e ?? ""}`;
    if (/NotAllowed|Permission|denied/i.test(t))
      return "ক্যামেরার অনুমতি দেওয়া হয়নি। ব্রাউজারের সাইট সেটিংস থেকে Camera → Allow করে রিলোড করুন।";
    if (/NotFound|DevicesNotFound/i.test(t)) return "এই ডিভাইসে ক্যামেরা পাওয়া যায়নি।";
    if (/NotReadable|TrackStart|in use/i.test(t))
      return "ক্যামেরা অন্য অ্যাপ/ট্যাবে ব্যবহৃত হচ্ছে। সেটি বন্ধ করে আবার চেষ্টা করুন।";
    if (/InsecureContext|HTTPS/i.test(t)) return "ক্যামেরার জন্য HTTPS লিংক দরকার।";
    return e?.message || "ক্যামেরা চালু করা যায়নি।";
  }

  function captureFrame(video, maxWidth = 720) {
    const ratio = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : 4 / 3;
    const w = Math.min(maxWidth, video.videoWidth || maxWidth);
    const h = Math.round(w / ratio);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    canvas.getContext("2d").drawImage(video, 0, 0, w, h);
    return canvas;
  }

  /* Resize a photo to a square-ish JPEG data URL for storage. */
  function imageToDataUrl(fileOrCanvas, { size = 520, quality = 0.86 } = {}) {
    return new Promise((resolve, reject) => {
      const draw = (img) => {
        const side = Math.min(img.width, img.height);
        const sx = (img.width - side) / 2;
        const sy = (img.height - side) / 2;
        const canvas = document.createElement("canvas");
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, size, size);
        ctx.drawImage(img, sx, sy, side, side, 0, 0, size, size);
        resolve(canvas.toDataURL("image/jpeg", quality));
      };
      if (fileOrCanvas instanceof HTMLCanvasElement) return draw(fileOrCanvas);
      const url = URL.createObjectURL(fileOrCanvas);
      const img = new Image();
      img.onload = () => {
        draw(img);
        URL.revokeObjectURL(url);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("ছবিটি খোলা যায়নি।"));
      };
      img.src = url;
    });
  }

  /* ------------------------------------------------------------------ */
  /* UI utilities                                                        */
  /* ------------------------------------------------------------------ */
  const $ = (id) => document.getElementById(id);
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const BN_DIGITS = ["০", "১", "২", "৩", "৪", "৫", "৬", "৭", "৮", "৯"];
  const bn = (v) => String(v ?? "").replace(/[0-9]/g, (d) => BN_DIGITS[+d]);

  function toast(message, type = "info", ms = 3800) {
    let host = document.getElementById("toastHost");
    if (!host) {
      host = document.createElement("div");
      host.id = "toastHost";
      host.className = "toast-host";
      document.body.appendChild(host);
    }
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.textContent = message;
    host.appendChild(el);
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 300);
    }, ms);
  }

  function setBusy(btn, busy, busyLabel) {
    if (!btn) return;
    if (busy) {
      btn.dataset.label = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span>${esc(busyLabel || "অপেক্ষা করুন…")}`;
    } else if (btn.dataset.label) {
      btn.innerHTML = btn.dataset.label;
      btn.disabled = false;
    }
  }

  function fmtDate(value, opts = { dateStyle: "medium" }) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return esc(value);
    return new Intl.DateTimeFormat("bn-BD", opts).format(d);
  }

  window.School = {
    cfg,
    rpc,
    sess,
    qrSvg,
    qrDataUrl,
    qrCanvas,
    loadModels,
    descriptorFrom,
    distance,
    startCamera,
    cameraErrorMessage,
    captureFrame,
    imageToDataUrl,
    $,
    esc,
    bn,
    toast,
    setBusy,
    fmtDate,
  };
})();
