/* ID card renderer — one markup source for admin preview, verify page, PDF. */
(function () {
  const S = window.School;

  function fullName(s) {
    return s?.name || "—";
  }

  function initials(name) {
    const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] || "" : "");
  }

  /**
   * Build the ID card HTML.
   * @param {object} student  row with name, student_id, class_name, section, roll_no,
   *                          photo_data, card_token, card_no, session, valid_until
   * @param {object} school   settings row (school_name, address, logo_data, principal_name…)
   * @param {object} opts     { verifyBase, theme }
   */
  function render(student, school = {}, opts = {}) {
    const s = student || {};
    const sc = school || {};
    const theme = opts.theme || sc.theme_color || "#0b1730";
    const verifyBase =
      opts.verifyBase || (sc.app_url ? String(sc.app_url).replace(/\/$/, "") : location.origin);
    const verifyUrl = `${verifyBase}/card?t=${encodeURIComponent(s.card_token || "")}`;
    const initialsText = S.esc(initials(s.name));
    const photo = s.photo_data
      ? `<img src="${s.photo_data}" alt="${S.esc(s.name)}">`
      : `<div class="id-photo-fallback">${initialsText}</div>`;
    const logo = sc.logo_data
      ? `<img src="${sc.logo_data}" alt="">`
      : S.esc((sc.school_name_en || sc.school_name || "S").slice(0, 1));

    const cls = [s.class_name, s.section ? `(শাখা ${s.section})` : ""].filter(Boolean).join(" ") || "—";
    let qr = "";
    try {
      if (s.card_token) qr = S.qrSvg(verifyUrl, 160);
    } catch (e) {
      qr = "";
    }

    return `
  <article class="id-card" data-theme="${S.esc(theme)}" style="--card-accent:${S.esc(theme)}">
    <div class="id-head" style="background:radial-gradient(130% 150% at 100% 0%, color-mix(in srgb, ${S.esc(theme)} 62%, #1d4ed8) 0%, ${S.esc(theme)} 58%, #070f22 100%)">
      <div class="id-head-top">
        <div class="id-logo">${logo}</div>
        <div style="min-width:0">
          <div class="id-school">${S.esc(sc.school_name || "বিদ্যালয়")}</div>
          <div class="id-school-en">${S.esc(sc.school_name_en || "")}</div>
          <div class="id-address">${S.esc(sc.address || "")}${sc.phone ? " • " + S.esc(sc.phone) : ""}</div>
        </div>
      </div>
      <div class="id-chip" aria-hidden="true"></div>
      <div class="id-photo-wrap">${photo}</div>
    </div>
    <div class="id-body">
      <div class="id-name">${S.esc(fullName(s))}</div>
      <div class="id-role">শিক্ষার্থী পরিচয়পত্র · STUDENT IDENTITY CARD</div>
      <div class="id-fields">
        <div><div class="id-field-label">Student ID</div><div class="id-field-value mono">${S.esc(s.student_id || "—")}</div></div>
        <div><div class="id-field-label">Card No.</div><div class="id-field-value mono">${S.esc(s.card_no || "—")}</div></div>
        <div><div class="id-field-label">শ্রেণি</div><div class="id-field-value">${S.esc(cls)}</div></div>
        <div><div class="id-field-label">রোল</div><div class="id-field-value">${S.esc(s.roll_no || "—")}</div></div>
        <div><div class="id-field-label">রক্তের গ্রুপ</div><div class="id-field-value">${S.esc(s.blood_group || "—")}</div></div>
        <div><div class="id-field-label">শিক্ষাবর্ষ</div><div class="id-field-value">${S.esc(s.session || sc.session || "—")}</div></div>
      </div>
      <div class="id-qr-row">
        <div class="id-qr">${qr}</div>
        <div class="id-qr-meta">
          <div class="id-qr-title">গেটে স্ক্যান করুন</div>
          <div class="id-qr-text">QR স্ক্যান করে সেকেন্ডে উপস্থিতি। কোডটি ব্যক্তিগত; অন্যের সাথে শেয়ার করবেন না।</div>
          <div class="id-token">${S.esc(s.card_token || "")}</div>
        </div>
      </div>
    </div>
    <div class="id-foot">
      <div class="id-sign"><div class="id-sign-line"></div><b>${S.esc((sc.principal_name || "").split(" ").slice(-1)[0] || "")}</b>প্রধান শিক্ষক</div>
      <div style="text-align:right">
        <div class="id-valid">মেয়াদ: ${S.esc(s.valid_until ? S.fmtDate(s.valid_until, { dateStyle: "medium" }) : "—")}</div>
        <div class="id-token" style="margin-top:2px">${S.esc(sc.eiin ? "EIIN: " + sc.eiin : "")}</div>
      </div>
      <div class="id-sign"><div class="id-sign-line"></div><b>${S.esc(initials(s.name))}</b>শিক্ষার্থীর স্বাক্ষর</div>
    </div>
    <div class="id-gold-bar"></div>
  </article>`;
  }

  window.SchoolCard = { render };
})();
