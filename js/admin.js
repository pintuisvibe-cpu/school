/* Admin console: PIN gate, student CRUD, face enrolment, attendance, settings. */
(function () {
  const S = window.School;
  const $ = S.$;
  const state = {
    pin: S.sess.pin,
    students: [],
    settings: {},
    attendance: [],
    editing: null,
    photoData: "",
    descriptor: null,
    stream: null,
  };

  /* ---------------------------------------------------------------- */
  /* Boot                                                             */
  /* ---------------------------------------------------------------- */
  function showApp() {
    $("loginView").classList.add("hidden");
    $("appView").classList.remove("hidden");
    $("pageSchool").textContent = state.settings.school_name || "ড্যাশবোর্ড";
    $("brandName").textContent = state.settings.school_name || "স্কুল আইডি কার্ড";
    $("brandMark").textContent = (state.settings.school_name_en || state.settings.school_name || "S").slice(0, 1);
    if (state.settings.logo_data) {
      $("brandMark").innerHTML = `<img src="${state.settings.logo_data}" alt="">`;
    }
    const tab = (location.hash || "#overview").replace("#", "");
    switchTab(["overview", "students", "attendance", "settings"].includes(tab) ? tab : "overview");
    refreshAll();
  }

  function showLogin(msg) {
    $("loginView").classList.remove("hidden");
    $("appView").classList.add("hidden");
    if (msg) S.toast(msg, "error");
    setTimeout(() => $("pinInput").focus(), 60);
  }

  async function boot() {
    try {
      state.settings = (await S.rpc("public_settings")) || {};
    } catch (err) {
      S.toast(err.message, "error", 6000);
    }
    if (!state.pin) return showLogin();
    try {
      const check = await S.rpc("admin_login", { p_pin: state.pin });
      if (check && check.ok) showApp();
      else {
        S.sess.pin = "";
        state.pin = "";
        showLogin("PIN আর বৈধ নয়, আবার দিয়ে প্রবেশ করুন।");
      }
    } catch (err) {
      showLogin(err.message);
    }
  }

  $("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pin = $("pinInput").value.trim();
    if (!/^\d{4,12}$/.test(pin)) return S.toast("PIN ৪–১২ ডিজিটের সংখ্যা হতে হবে।", "error");
    S.setBusy($("loginBtn"), true, "যাচাই হচ্ছে…");
    try {
      const check = await S.rpc("admin_login", { p_pin: pin });
      if (!check || !check.ok) throw new Error("PIN ভুল হয়েছে।");
      S.sess.pin = pin;
      state.pin = pin;
      $("pinInput").value = "";
      showApp();
      S.toast("স্বাগতম!", "success");
    } catch (err) {
      S.toast(err.message, "error");
    } finally {
      S.setBusy($("loginBtn"), false);
    }
  });

  $("lockBtn").addEventListener("click", () => {
    S.sess.pin = "";
    state.pin = "";
    stopCamera();
    showLogin("লগআউট হয়েছে।");
  });

  /* ---------------------------------------------------------------- */
  /* Tabs                                                             */
  /* ---------------------------------------------------------------- */
  function switchTab(name) {
    document.querySelectorAll("#tabs .tab").forEach((t) =>
      t.setAttribute("aria-selected", String(t.dataset.tab === name))
    );
    document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
    $("panel-" + name)?.classList.remove("hidden");
    if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
    if (name === "attendance") loadAttendance($("attDate").value || "");
    if (name === "students") loadStudents();
  }
  $("tabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (btn) switchTab(btn.dataset.tab);
  });
  window.addEventListener("hashchange", () => {
    const tab = location.hash.replace("#", "");
    if (["overview", "students", "attendance", "settings"].includes(tab)) switchTab(tab);
  });

  /* ---------------------------------------------------------------- */
  /* Data loading                                                     */
  /* ---------------------------------------------------------------- */
  async function loadStudents() {
    try {
      const res = await S.rpc("admin_list_students", { p_pin: state.pin });
      if (res.status !== "success") throw new Error(res.reason || "তালিকা আসেনি।");
      state.students = res.students || [];
      renderStudents();
      $("studentsCount").textContent = `${S.bn(state.students.length)} জন শিক্ষার্থী`;
      fillClassList();
      renderManualOptions();
    } catch (err) {
      S.toast(err.message, "error");
    }
  }

  function photoCell(s) {
    if (s.photo_data) return `<img class="avatar" src="${s.photo_data}" alt="">`;
    return `<div class="avatar">${S.esc((s.name || "?").slice(0, 1))}</div>`;
  }

  function renderStudents() {
    const q = ($("studentSearch").value || "").trim().toLowerCase();
    const rows = state.students.filter(
      (s) =>
        !q ||
        [s.name, s.student_id, s.class_name, s.section, s.roll_no, s.card_no]
          .join(" ")
          .toLowerCase()
          .includes(q)
    );
    $("studentsRows").innerHTML = rows.length
      ? rows
          .map(
            (s) => `<tr>
        <td><div class="row-person">${photoCell(s)}<div><b>${S.esc(s.name)}</b><div class="tiny muted mono">${S.esc(s.student_id)}</div></div></div></td>
        <td>${S.esc(s.class_name)}${s.section ? " / " + S.esc(s.section) : ""}</td>
        <td class="td-mono">${S.esc(s.card_no || "—")}</td>
        <td>${s.has_face ? '<span class="pill pill-ok">✓ আছে</span>' : '<span class="pill pill-warn">নেই</span>'}</td>
        <td>${s.active ? '<span class="pill">সক্রিয়</span>' : '<span class="pill pill-muted">নিষ্ক্রিয়</span>'}</td>
        <td><div class="flex gap-6">
          <a class="btn btn-ghost btn-sm" href="/cards?id=${encodeURIComponent(s.student_id)}">কার্ড</a>
          <button class="btn btn-ghost btn-sm" data-edit="${S.esc(s.student_id)}">এডিট</button>
          <button class="btn btn-danger btn-sm" data-del="${S.esc(s.student_id)}">মুছুন</button>
        </div></td>
      </tr>`
          )
          .join("")
      : `<tr><td colspan="6" class="empty"><b>কোনো শিক্ষার্থী নেই</b>ডান পাশের ফর্ম দিয়ে প্রথম শিক্ষার্থী যোগ করুন।</td></tr>`;
  }

  $("studentSearch").addEventListener("input", renderStudents);

  $("studentsRows").addEventListener("click", async (e) => {
    const editId = e.target.dataset?.edit;
    const delId = e.target.dataset?.del;
    if (editId) return startEdit(editId);
    if (!delId) return;
    const s = state.students.find((x) => x.student_id === delId);
    if (!confirm(`"${s?.name || delId}" কে মুছে ফেলবেন? উপস্থিতির রেকর্ডও মুছে যাবে।`)) return;
    try {
      const res = await S.rpc("admin_delete_student", { p_pin: state.pin, p_student_id: delId });
      if (res.status !== "success") throw new Error(res.reason);
      S.toast("শিক্ষার্থী মুছে ফেলা হয়েছে", "success");
      await loadStudents();
      refreshOverview();
    } catch (err) {
      S.toast(err.message, "error");
    }
  });

  async function loadAttendance(dateStr) {
    try {
      const res = await S.rpc("admin_attendance", {
        p_pin: state.pin,
        p_date: dateStr || null,
      });
      if (res.status !== "success") throw new Error(res.reason || "রিপোর্ট আসেনি।");
      state.attendance = res.rows || [];
      const day = res.date;
      $("attDate").value = day || "";
      $("attSub").textContent = `${S.fmtDate(day)} • ${S.bn(state.attendance.length)} জন উপস্থিত`;
      renderAttendance();
      if (day && day === new Date().toISOString().slice(0, 10)) renderOverviewAttendance();
    } catch (err) {
      S.toast(err.message, "error");
    }
  }

  function methodPill(m) {
    return m === "manual"
      ? '<span class="pill pill-warn">ম্যানুয়াল</span>'
      : '<span class="pill pill-ok">QR + ফেস</span>';
  }

  function renderAttendance() {
    $("attRows").innerHTML = state.attendance.length
      ? state.attendance
          .map(
            (r) => `<tr>
        <td><b>${S.esc(r.name)}</b></td>
        <td class="td-mono">${S.esc(r.student_id)}</td>
        <td>${S.esc(r.class_name || "—")}</td>
        <td class="td-mono">${S.esc(r.time)}</td>
        <td>${methodPill(r.method)}</td>
        <td><span class="pill pill-ok">${S.esc(r.status || "Present")}</span></td>
        <td class="no-print"><button class="btn btn-danger btn-sm" data-unmark="${S.esc(r.student_id)}">সরান</button></td>
      </tr>`
          )
          .join("")
      : `<tr><td colspan="7" class="empty"><b>এই দিনে কোনো উপস্থিতি নেই</b>গেট স্ক্যানার দিয়ে উপস্থিতি নিন, অথবা নিচ থেকে ম্যানুয়ালি যোগ করুন।</td></tr>`;
  }

  $("attRows").addEventListener("click", async (e) => {
    const id = e.target.dataset?.unmark;
    if (!id) return;
    if (!confirm("এই উপস্থিতি রেকর্ডটি সরাবেন?")) return;
    try {
      const res = await S.rpc("admin_unmark", { p_pin: state.pin, p_student_id: id });
      if (res.status !== "success") throw new Error(res.reason);
      S.toast("সরানো হয়েছে", "success");
      loadAttendance($("attDate").value);
      refreshOverview();
    } catch (err) {
      S.toast(err.message, "error");
    }
  });

  $("attDate").addEventListener("change", () => loadAttendance($("attDate").value));
  $("attToday").addEventListener("click", () => loadAttendance(""));
  $("attCsv").addEventListener("click", () => downloadCsv(state.attendance, $("attDate").value || "today"));
  $("attPrint").addEventListener("click", () => window.print());

  function downloadCsv(rows, name) {
    const head = ["Student ID", "Name", "Class", "Date", "Time", "Method", "Status"];
    const body = rows.map((r) => [
      r.student_id,
      r.name,
      r.class_name || "",
      r.date || $("attDate").value || "",
      r.time,
      r.method,
      r.status,
    ]);
    const csv =
      "\uFEFF" +
      [head, ...body]
        .map((row) => row.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(","))
        .join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `attendance-${name}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  $("quickCsv").addEventListener("click", () => downloadCsv(state.attendance, "today"));

  function renderManualOptions() {
    $("manualStudent").innerHTML =
      '<option value="">শিক্ষার্থী বাছুন</option>' +
      state.students
        .map(
          (s) =>
            `<option value="${S.esc(s.student_id)}">${S.esc(s.name)} — ${S.esc(s.class_name)}</option>`
        )
        .join("");
  }

  $("manualMark").addEventListener("click", async () => {
    const id = $("manualStudent").value;
    if (!id) return S.toast("আগে শিক্ষার্থী বাছুন।", "warn");
    try {
      const res = await S.rpc("admin_mark", { p_pin: state.pin, p_student_id: id, p_status: "Present" });
      if (res.status !== "success") throw new Error(res.reason);
      S.toast("উপস্থিতি যোগ হয়েছে", "success");
      loadAttendance($("attDate").value);
      refreshOverview();
    } catch (err) {
      S.toast(err.message, "error");
    }
  });

  function fillClassList() {
    const classes = [...new Set(state.students.map((s) => s.class_name).filter(Boolean))];
    const dl = $("classList");
    if (!classes.length) return;
    dl.innerHTML = classes.map((c) => `<option value="${S.esc(c)}">`).join("");
  }

  /* ---------------------------------------------------------------- */
  /* Overview                                                         */
  /* ---------------------------------------------------------------- */
  async function refreshOverview() {
    await loadStudents();
    await loadAttendance("");
    const total = state.students.filter((s) => s.active).length;
    const present = state.attendance.length;
    $("kpiStudents").textContent = S.bn(total);
    $("kpiPresent").textContent = S.bn(present);
    $("kpiAbsent").textContent = S.bn(Math.max(0, total - present));
    $("kpiPct").textContent = total ? `উপস্থিতির হার ${S.bn(Math.round((present / total) * 100))}%` : "—";
    $("ovDate").textContent = S.fmtDate(new Date().toISOString(), { dateStyle: "full" });
    renderOverviewAttendance();
    renderManualOptions();
  }

  function renderOverviewAttendance() {
    const rows = [...state.attendance].slice(0, 8);
    $("ovRows").innerHTML = rows.length
      ? rows
          .map(
            (r) => `<tr><td><div class="row-person">
              <div class="avatar avatar-sm">${S.esc((r.name || "?").slice(0, 1))}</div><b>${S.esc(r.name)}</b></div></td>
              <td>${S.esc(r.class_name || "—")}</td><td class="td-mono">${S.esc(r.time)}</td><td>${methodPill(r.method)}</td></tr>`
          )
          .join("")
      : `<tr><td colspan="4" class="empty"><b>আজ এখনো কেউ আসেনি</b>গেট স্ক্যানার চালু করুন।</td></tr>`;
  }

  async function refreshAll() {
    try {
      state.settings = (await S.rpc("admin_get_settings", { p_pin: state.pin })).settings || state.settings;
      fillSettingsForm();
    } catch (err) {
      S.toast(err.message, "error");
    }
    await refreshOverview();
  }

  $("ovRefresh").addEventListener("click", refreshAll);

  /* ---------------------------------------------------------------- */
  /* Student editor + face enrolment                                  */
  /* ---------------------------------------------------------------- */
  function setPhoto(dataUrl) {
    state.photoData = dataUrl || "";
    const img = $("photoPreview");
    if (state.photoData) {
      img.src = state.photoData;
      img.classList.remove("hidden");
      $("photoPlaceholder").classList.add("hidden");
    } else {
      img.removeAttribute("src");
      img.classList.add("hidden");
      $("photoPlaceholder").classList.remove("hidden");
    }
  }

  function resetEditor() {
    state.editing = null;
    $("studentForm").reset();
    $("fOriginalId").value = "";
    setPhoto("");
    setDescriptor(null);
    $("editorTitle").textContent = "নতুন শিক্ষার্থী";
    $("cancelEdit").classList.add("hidden");
    $("reEnrollBtn").classList.add("hidden");
    $("rotateTokenBtn").classList.add("hidden");
    $("fStudentId").disabled = false;
    $("fCardNo").value = "";
    $("saveStudentBtn").textContent = "সংরক্ষণ করুন";
    $("fSession").value = state.settings.session || "2026";
    $("fValid").value = state.settings.card_valid_until || "";
  }

  function toggleEditActions(on) {
    $("reEnrollBtn").classList.toggle("hidden", !on);
    $("rotateTokenBtn").classList.toggle("hidden", !on);
  }

  $("reEnrollBtn").addEventListener("click", async () => {
    if (!state.editing) return;
    if (!state.descriptor) return S.toast("আগে নতুন ছবি তুলে মুখের ছাপ তৈরি করুন।", "warn");
    if (!$("consent").checked) return S.toast("সম্মতির টিক দিন।", "warn");
    try {
      const res = await S.rpc("admin_set_face", {
        p_pin: state.pin,
        p_student_id: state.editing.student_id,
        p_descriptor: state.descriptor,
      });
      if (res.status !== "success") throw new Error(res.reason);
      S.toast("মুখের ছাপ আপডেট হয়েছে", "success");
      await loadStudents();
      setDescriptor(null);
    } catch (err) {
      S.toast(err.message, "error");
    }
  });

  $("rotateTokenBtn").addEventListener("click", async () => {
    if (!state.editing) return;
    if (!confirm("নতুন QR টোকেন তৈরি করলে পুরোনো কার্ডের QR আর কাজ করবে না। চালিয়ে যাবেন?")) return;
    try {
      const res = await S.rpc("admin_set_token", {
        p_pin: state.pin,
        p_student_id: state.editing.student_id,
      });
      if (res.status !== "success") throw new Error(res.reason);
      S.toast("নতুন QR তৈরি — কার্ড আবার প্রিন্ট করুন", "success");
      await loadStudents();
      $("faceStatus").innerHTML = `<span style="color:var(--ok)">নতুন টোকেন: </span><span class="mono">${S.esc(res.card_token)}</span>`;
    } catch (err) {
      S.toast(err.message, "error");
    }
  });

  function setDescriptor(d) {
    state.descriptor = d;
    $("faceStatus").innerHTML = d
      ? `<span style="color:var(--ok);font-weight:700">✓ মুখের ছাপ তৈরি (${S.bn(d.length)} সংখ্যা)</span>`
      : "মুখের descriptor এখনো তৈরি হয়নি।";
  }

  function startEdit(id) {
    const s = state.students.find((x) => x.student_id === id);
    if (!s) return;
    state.editing = s;
    $("fOriginalId").value = s.student_id;
    $("fStudentId").value = s.student_id;
    $("fStudentId").disabled = true;
    $("fCardNo").value = s.card_no || "";
    $("fName").value = s.name || "";
    $("fClass").value = s.class_name || "";
    $("fSection").value = s.section || "";
    $("fRoll").value = s.roll_no || "";
    $("fBlood").value = s.blood_group || "";
    $("fDob").value = s.date_of_birth || "";
    $("fPhone").value = s.phone || "";
    $("fFather").value = s.father_name || "";
    $("fMother").value = s.mother_name || "";
    $("fAddress").value = s.address || "";
    $("fSession").value = s.session || "";
    $("fValid").value = s.valid_until || "";
    setPhoto(s.photo_data || "");
    setDescriptor(null);
    $("editorTitle").textContent = `এডিট: ${s.name}`;
    $("cancelEdit").classList.remove("hidden");
    toggleEditActions(true);
    $("saveStudentBtn").textContent = "পরিবর্তন সংরক্ষণ";
    $("editorCard").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  $("cancelEdit").addEventListener("click", resetEditor);
  $("quickAdd").addEventListener("click", () => {
    switchTab("students");
    resetEditor();
    $("fName").focus();
  });

  $("pickPhotoBtn").addEventListener("click", () => $("photoFile").click());
  $("photoFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const dataUrl = await S.imageToDataUrl(file);
      setPhoto(dataUrl);
      await descriptorFromPhoto(dataUrl);
    } catch (err) {
      S.toast(err.message, "error");
    }
  });

  async function descriptorFromPhoto(dataUrl) {
    $("faceStatus").innerHTML = '<span class="spinner spinner-dark"></span> মুখ বিশ্লেষণ হচ্ছে…';
    try {
      const img = await new Promise((resolve, reject) => {
        const i = new Image();
        i.onload = () => resolve(i);
        i.onerror = () => reject(new Error("ছবি পড়া যায়নি।"));
        i.src = dataUrl;
      });
      const d = await S.descriptorFrom(img);
      setDescriptor(d);
    } catch (err) {
      setDescriptor(null);
      $("faceStatus").innerHTML = `<span style="color:var(--danger)">${S.esc(err.message)}</span> ছবি ঠিক থাকলে সংরক্ষণ করতে পারেন; পরে ‘শুধু মুখ নিবন্ধন’ দিয়ে আবার চেষ্টা করুন।`;
    }
  }

  function stopCamera() {
    if (state.stream) {
      state.stream.getTracks().forEach((t) => t.stop());
      state.stream = null;
    }
    $("video").classList.add("hidden");
    $("snapBtn").classList.add("hidden");
  }

  $("camBtn").addEventListener("click", async () => {
    try {
      stopCamera();
      state.stream = await S.startCamera($("video"), { facing: "user" });
      $("video").classList.remove("hidden");
      $("snapBtn").classList.remove("hidden");
      $("faceStatus").textContent = "মুখ ফ্রেমে রেখে ‘ছবি তুলুন’ চাপুন।";
    } catch (err) {
      S.toast(S.cameraErrorMessage(err), "error", 6000);
    }
  });

  $("snapBtn").addEventListener("click", async () => {
    if (!state.stream) return;
    const canvas = S.captureFrame($("video"), 640);
    stopCamera();
    try {
      const dataUrl = await S.imageToDataUrl(canvas);
      setPhoto(dataUrl);
      await descriptorFromPhoto(dataUrl);
    } catch (err) {
      S.toast(err.message, "error");
    }
  });

  $("studentForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.photoData && !state.editing) return S.toast("শিক্ষার্থীর ছবি দিন বা তুলুন।", "warn");
    if (state.descriptor && !$("consent").checked)
      return S.toast("মুখের ছাপ সংরক্ষণে অভিভাবকের সম্মতি টিক দিন।", "warn");
    const payload = {
      student_id: ($("fOriginalId").value || $("fStudentId").value).trim(),
      name: $("fName").value.trim(),
      class_name: $("fClass").value.trim(),
      section: $("fSection").value.trim(),
      roll_no: $("fRoll").value.trim(),
      blood_group: $("fBlood").value,
      date_of_birth: $("fDob").value,
      phone: $("fPhone").value.trim(),
      father_name: $("fFather").value.trim(),
      mother_name: $("fMother").value.trim(),
      address: $("fAddress").value.trim(),
      session: $("fSession").value.trim(),
      valid_until: $("fValid").value,
      photo_data: state.photoData || (state.editing ? state.editing.photo_data || "" : ""),
      active: true,
    };
    if (state.descriptor && $("consent").checked) payload.face_descriptor = state.descriptor;
    S.setBusy($("saveStudentBtn"), true, "সংরক্ষণ হচ্ছে…");
    try {
      const res = await S.rpc("admin_save_student", { p_pin: state.pin, p_student: payload });
      if (res.status !== "success") throw new Error(res.reason || "সংরক্ষণ ব্যর্থ");
      S.toast(
        state.editing ? "তথ্য আপডেট হয়েছে" : `সংরক্ষিত — কার্ড নং ${res.card_no || ""}`,
        "success"
      );
      resetEditor();
      await refreshOverview();
    } catch (err) {
      S.toast(err.message, "error", 6000);
    } finally {
      S.setBusy($("saveStudentBtn"), false);
    }
  });

  /* ---------------------------------------------------------------- */
  /* Settings                                                         */
  /* ---------------------------------------------------------------- */
  function fillSettingsForm() {
    const s = state.settings || {};
    $("sName").value = s.school_name || "";
    $("sNameEn").value = s.school_name_en || "";
    $("sEiin").value = s.eiin || "";
    $("sAddress").value = s.address || "";
    $("sPhone").value = s.phone || "";
    $("sEmail").value = s.email || "";
    $("sPrincipal").value = s.principal_name || "";
    $("sSession").value = s.session || "";
    $("sValid").value = s.card_valid_until || "";
    $("sTheme").value = s.theme_color || "#1d4ed8";
    $("sAppUrl").value = s.app_url || location.origin;
    if (s.logo_data) {
      $("logoPreview").src = s.logo_data;
      $("logoPreview").classList.remove("hidden");
    }
    $("infoHost").textContent = (S.cfg.supabaseUrl || "").replace(/^https?:\/\//, "").split(".")[0];
  }

  let logoData = "";
  $("logoFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    logoData = await S.imageToDataUrl(file, { size: 240, quality: 0.9 });
    $("logoPreview").src = logoData;
    $("logoPreview").classList.remove("hidden");
    S.toast("লোগো প্রস্তুত — ‘সেটিংস সংরক্ষণ’ চাপুন।", "info");
  });

  $("settingsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      school_name: $("sName").value.trim(),
      school_name_en: $("sNameEn").value.trim(),
      eiin: $("sEiin").value.trim(),
      address: $("sAddress").value.trim(),
      phone: $("sPhone").value.trim(),
      email: $("sEmail").value.trim(),
      principal_name: $("sPrincipal").value.trim(),
      session: $("sSession").value.trim(),
      card_valid_until: $("sValid").value,
      theme_color: $("sTheme").value,
      app_url: $("sAppUrl").value.trim(),
    };
    if (logoData) payload.logo_data = logoData;
    S.setBusy($("saveSettingsBtn"), true, "সংরক্ষণ হচ্ছে…");
    try {
      const res = await S.rpc("admin_save_settings", { p_pin: state.pin, p_settings: payload });
      if (res.status !== "success") throw new Error(res.reason);
      logoData = "";
      S.toast("স্কুলের তথ্য সংরক্ষিত হয়েছে", "success");
      await refreshAll();
    } catch (err) {
      S.toast(err.message, "error");
    } finally {
      S.setBusy($("saveSettingsBtn"), false);
    }
  });

  $("pinForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const p1 = $("newPin").value.trim();
    const p2 = $("newPin2").value.trim();
    if (!/^\d{4,12}$/.test(p1)) return S.toast("PIN ৪–১২ ডিজিটের হতে হবে।", "warn");
    if (p1 !== p2) return S.toast("দুইবার একই PIN লিখুন।", "warn");
    try {
      const res = await S.rpc("admin_save_settings", {
        p_pin: state.pin,
        p_settings: {},
        p_new_pin: p1,
      });
      if (res.status !== "success") throw new Error(res.reason);
      S.sess.pin = p1;
      state.pin = p1;
      $("pinForm").reset();
      S.toast("PIN পরিবর্তিত হয়েছে — নতুন PIN মনে রাখুন।", "success", 6000);
    } catch (err) {
      S.toast(err.message, "error");
    }
  });

  $("resetDemo").addEventListener("click", async () => {
    if (!confirm("সব শিক্ষার্থী ও উপস্থিতি মুছে ফেলবেন? এটি ফেরানো যাবে না।")) return;
    if (prompt('নিশ্চিত করতে "DELETE" লিখুন') !== "DELETE") return;
    try {
      const res = await S.rpc("admin_reset_students", { p_pin: state.pin });
      if (res.status !== "success") throw new Error(res.reason);
      S.toast("ডেটা মুছে ফেলা হয়েছে", "success");
      await refreshAll();
    } catch (err) {
      S.toast(err.message, "error");
    }
  });

  $("exportStudents").addEventListener("click", () => {
    const head = ["student_id", "name", "class", "section", "roll", "father", "mother", "phone", "blood", "card_no", "card_token"];
    const rows = state.students.map((s) => [
      s.student_id, s.name, s.class_name, s.section, s.roll_no, s.father_name, s.mother_name, s.phone, s.blood_group, s.card_no, s.card_token,
    ]);
    const csv = "\uFEFF" + [head, ...rows].map((r) => r.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = "students.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });

  /* ---------------------------------------------------------------- */
  boot();
})();
