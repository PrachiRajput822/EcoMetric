"use strict";

(() => {
  // ------------------------------------------------------------------ helpers
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  /** Build DOM nodes. Data is always inserted as text, never as HTML. */
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k === "svg") el.innerHTML = ICONS[v] || ""; // static, trusted icon markup only
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  const ICONS = {
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M12 7v6"/><path d="M12 17.5v.01"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M12 11v6"/><path d="M12 7.5v.01"/></svg>',
    blocking: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>',
    electricity: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/></svg>',
    water: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M12 3s6 6.7 6 11a6 6 0 0 1-12 0c0-4.3 6-11 6-11z"/></svg>',
    waste: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>',
    air: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M3 9h11a3 3 0 1 0-3-3M3 15h15a3 3 0 1 1-3 3M3 12h8"/></svg>',
    mobility: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="3" width="16" height="14" rx="3"/><path d="M4 11h16M8 21v-4M16 21v-4"/><circle cx="8.5" cy="14" r="0.5"/><circle cx="15.5" cy="14" r="0.5"/></svg>',
    resources: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M3 21h18M5 21V8l7-5 7 5v13M9 21v-6h6v6"/></svg>',
    custom: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M4 9h16M4 15h16M10 3v18"/></svg>',
  };

  const T = {
    en: {
      tagline: "Community and environmental data intelligence",
      step1: "Load dataset", step2: "Ask in plain language", step3: "Calculate with code", step4: "Chart and answer", step5: "Explain caveats",
      s1title: "Load a dataset", s1lede: "Pick an issue to load its sample data, or upload your own CSV or Excel file.",
      uploadTitle: "Upload your own data", chooseFile: "Choose file", continue: "Continue", back: "Back", ask: "Ask",
      s2title: "Ask in plain language", s2lede: "Ask in English or Hindi. The model only chooses the calculation; tested code does the maths.",
      plannerLabel: "Who reads the question", questionLabel: "Your question",
      s3title: "Calculate with code", s3lede: "The question became one structured tool call. DuckDB ran it, and pandas checked it independently.",
      s4title: "Chart and answer", s5title: "Explain caveats", s5lede: "Every caveat comes from a rule-based check on the data, never from the model.",
      auditTitle: "Answer audit log", changeData: "Change dataset", askAnother: "Ask another question",
      issues: { electricity: "Electricity", water: "Water usage", waste: "Waste collection", air: "Air quality", mobility: "Mobility", resources: "Campus resources" },
      loading: "Loading…", loaded: (t) => `${t} loaded.`, rows: "Rows", columns: "Columns", months: "Months", entities: "Groups",
      health: "Health check", columnsTitle: "Columns", preview: "First rows", role: "Role", unit: "Unit", missing: "Blank",
      source: { synthetic: "Synthetic sample", official: "Official", "user-entered": "User upload" },
      modes: { auto: "Auto", gemini: "Gemma 4 online", ollama: "Gemma 4 offline", rules: "Rules only" },
      modeHint: {
        auto: (n) => `Auto uses ${n} right now.`,
        gemini: () => "Gemma 4 (gemma-4-26b-a4b-it) through the Gemini API picks the tool with native function calling.",
        ollama: () => "Gemma 4 E2B runs on this computer through Ollama, so no data leaves the machine.",
        rules: () => "A rule-based parser picks the tool. No AI model is used.",
      },
      unavailable: "not available",
      calculating: "Calculating…", askEmpty: "Type a question first.", reloadData: "The dataset is no longer loaded. Go back and load it again.",
      readBy: "Read by", time: "Time", toolCall: "Tool call", sql: "Query that ran", method: "Method", period: "Period",
      crossOk: (n) => `DuckDB and pandas agree (${n} values compared)`, crossFail: "DuckDB and pandas disagree",
      rowsUsed: "Rows used", rowsSkipped: "Rows skipped", evidence: "Evidence rows", showing: (a, b) => `Showing ${a} of ${b} rows used in the calculation.`,
      noCalc: "No calculation was run, because the data cannot answer this question.",
      firstAttempt: "The model's first tool call was rejected by validation and replaced:",
      narrUsed: "Worded by Gemma 4. Every number was checked against the verified result.",
      narrNot: "Answer text generated directly from the verified result.",
      resultTable: "Result table", answer: "Answer", confidence: "Confidence",
      sev: { blocking: "Cannot answer", warning: "Check this", info: "Note" },
      noCaveats: "No problems were found in the data used for this answer.",
      auditEmpty: "No answers logged yet.", when: "When", question: "Question", tool: "Tool",
      fileTooBig: (mb) => `File is larger than ${mb} MB.`, fileType: "Only .csv and .xlsx files are supported.",
      uploadHint: (mb) => `CSV or Excel, up to ${mb} MB. One row per reading, with a month or date column.`,
      ms: "ms",
    },
    hi: {
      tagline: "समुदाय और पर्यावरण डेटा इंटेलिजेंस",
      step1: "डेटासेट लोड करें", step2: "सरल भाषा में पूछें", step3: "कोड से गणना", step4: "चार्ट और उत्तर", step5: "सावधानियां",
      s1title: "डेटासेट लोड करें", s1lede: "नमूना डेटा लोड करने के लिए कोई विषय चुनें, या अपनी CSV या Excel फ़ाइल अपलोड करें।",
      uploadTitle: "अपना डेटा अपलोड करें", chooseFile: "फ़ाइल चुनें", continue: "आगे बढ़ें", back: "पीछे", ask: "पूछें",
      s2title: "सरल भाषा में पूछें", s2lede: "हिंदी या अंग्रेज़ी में पूछें। मॉडल केवल गणना चुनता है; गणित परखा हुआ कोड करता है।",
      plannerLabel: "प्रश्न कौन पढ़ेगा", questionLabel: "आपका प्रश्न",
      s3title: "कोड से गणना", s3lede: "प्रश्न एक संरचित टूल कॉल बना। DuckDB ने इसे चलाया और pandas ने स्वतंत्र रूप से जांचा।",
      s4title: "चार्ट और उत्तर", s5title: "सावधानियां", s5lede: "हर सावधानी डेटा पर नियम-आधारित जांच से आती है, मॉडल से नहीं।",
      auditTitle: "उत्तर ऑडिट लॉग", changeData: "डेटासेट बदलें", askAnother: "दूसरा प्रश्न पूछें",
      issues: { electricity: "बिजली", water: "पानी का उपयोग", waste: "कचरा संग्रह", air: "वायु गुणवत्ता", mobility: "आवागमन", resources: "कैंपस संसाधन" },
      loading: "लोड हो रहा है…", loaded: (t) => `${t} लोड हो गया।`, rows: "पंक्तियां", columns: "कॉलम", months: "महीने", entities: "समूह",
      health: "डेटा जांच", columnsTitle: "कॉलम", preview: "पहली पंक्तियां", role: "भूमिका", unit: "इकाई", missing: "खाली",
      source: { synthetic: "सिंथेटिक नमूना", official: "आधिकारिक", "user-entered": "उपयोगकर्ता अपलोड" },
      modes: { auto: "स्वचालित", gemini: "Gemma 4 ऑनलाइन", ollama: "Gemma 4 ऑफ़लाइन", rules: "केवल नियम" },
      modeHint: {
        auto: (n) => `स्वचालित मोड अभी ${n} का उपयोग कर रहा है।`,
        gemini: () => "Gemini API के माध्यम से Gemma 4 (gemma-4-26b-a4b-it) फ़ंक्शन कॉलिंग से टूल चुनता है।",
        ollama: () => "Gemma 4 E2B इसी कंप्यूटर पर Ollama से चलता है, इसलिए डेटा बाहर नहीं जाता।",
        rules: () => "नियम-आधारित पार्सर टूल चुनता है। कोई AI मॉडल उपयोग नहीं होता।",
      },
      unavailable: "उपलब्ध नहीं",
      calculating: "गणना हो रही है…", askEmpty: "पहले प्रश्न लिखें।", reloadData: "डेटासेट अब लोड नहीं है। पीछे जाकर फिर से लोड करें।",
      readBy: "किसने पढ़ा", time: "समय", toolCall: "टूल कॉल", sql: "चलाई गई क्वेरी", method: "विधि", period: "अवधि",
      crossOk: (n) => `DuckDB और pandas सहमत हैं (${n} मान जांचे गए)`, crossFail: "DuckDB और pandas असहमत हैं",
      rowsUsed: "उपयोग की गई पंक्तियां", rowsSkipped: "छोड़ी गई पंक्तियां", evidence: "प्रमाण पंक्तियां", showing: (a, b) => `गणना में उपयोग की गई ${b} में से ${a} पंक्तियां दिखाई जा रही हैं।`,
      noCalc: "कोई गणना नहीं चलाई गई, क्योंकि डेटा इस प्रश्न का उत्तर नहीं दे सकता।",
      firstAttempt: "मॉडल का पहला टूल कॉल जांच में अस्वीकार हुआ और बदला गया:",
      narrUsed: "Gemma 4 द्वारा लिखा गया। हर संख्या सत्यापित परिणाम से जांची गई।",
      narrNot: "उत्तर सीधे सत्यापित परिणाम से बनाया गया।",
      resultTable: "परिणाम तालिका", answer: "उत्तर", confidence: "विश्वसनीयता",
      sev: { blocking: "उत्तर संभव नहीं", warning: "जांचें", info: "नोट" },
      noCaveats: "इस उत्तर में उपयोग हुए डेटा में कोई समस्या नहीं मिली।",
      auditEmpty: "अभी कोई उत्तर दर्ज नहीं है।", when: "समय", question: "प्रश्न", tool: "टूल",
      fileTooBig: (mb) => `फ़ाइल ${mb} MB से बड़ी है।`, fileType: "केवल .csv और .xlsx फ़ाइलें समर्थित हैं।",
      uploadHint: (mb) => `CSV या Excel, अधिकतम ${mb} MB। हर रीडिंग की एक पंक्ति, महीने या तारीख के कॉलम के साथ।`,
      ms: "ms",
    },
  };

  const state = { lang: "en", mode: "auto", status: null, samples: [], dataset: null, result: null, step: 1, maxStep: 1, busy: false, plotted: false };
  const t = (k) => T[state.lang][k];

  const NUM = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
  function fmtCell(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "number") return Math.abs(v) >= 100 ? NUM.format(Math.round(v)) : NUM.format(v);
    return String(v);
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, { headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opts });
    let data = null;
    try { data = await res.json(); } catch (_) { /* non-JSON error */ }
    if (!res.ok) {
      const detail = data && data.detail;
      const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : `Request failed (${res.status})`;
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function setStatus(id, text, isError = false) {
    const el = $(id);
    el.textContent = text || "";
    el.classList.toggle("error", !!isError);
  }

  // ------------------------------------------------------------------ steps
  function renderSteps() {
    const ol = $("#stepList");
    ol.replaceChildren();
    for (let n = 1; n <= 5; n++) {
      const locked = n > state.maxStep;
      const current = n === state.step;
      const done = !locked && !current && n < state.maxStep;
      const num = h("span", { class: "num", svg: locked ? "lock" : done ? "check" : null });
      if (!locked && !done) num.textContent = String(n);
      const btn = h("button", {
        type: "button", class: "step-btn" + (done ? " done" : ""), "aria-current": current ? "step" : null,
        disabled: locked, onclick: () => goTo(n), "aria-label": `${n}. ${t("step" + n)}${locked ? " (locked)" : ""}`,
      }, num, h("span", { text: t("step" + n) }));
      ol.append(h("li", {}, btn));
    }
  }

  function goTo(n) {
    if (n > state.maxStep || n < 1) return;
    state.step = n;
    for (const p of $$(".panel")) p.hidden = Number(p.dataset.step) !== n;
    renderSteps();
    if (n === 4) drawChart();
    if (n === 5 && $("#auditBox").open) loadAudit();
    const heading = $(`.panel[data-step="${n}"] h1`);
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (heading) { heading.setAttribute("tabindex", "-1"); heading.focus({ preventScroll: true }); }
  }

  function unlock(n) {
    state.maxStep = Math.max(state.maxStep, n);
  }

  // ------------------------------------------------------------------ i18n
  function applyLang() {
    document.documentElement.lang = state.lang;
    for (const el of $$("[data-i18n]")) {
      const v = t(el.dataset.i18n);
      if (typeof v === "string") el.textContent = v;
    }
    for (const b of $$(".topbar .seg button")) b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang));
    if (state.status) $("#uploadHint").textContent = t("uploadHint")(state.status.limits.max_upload_mb);
    renderSteps();
    renderIssues();
    renderModelChip();
    renderPlanners();
    if (state.dataset) { renderDataset(); renderExamples(); }
    if (state.result) { renderCalc(); renderAnswer(); renderCaveats(); state.plotted = false; if (state.step === 4) drawChart(); }
  }

  // ------------------------------------------------------------------ status and planners
  function plannerById(id) { return (state.status?.planners || []).find((p) => p.id === id); }

  function renderModelChip() {
    const chip = $("#modelChip");
    if (!state.status) return;
    const id = state.mode === "auto" ? state.status.resolved_auto : state.mode;
    const p = plannerById(id);
    const ok = id !== "rules" && p && p.available;
    chip.classList.toggle("ok", !!ok);
    chip.classList.toggle("warn", !ok);
    $("#modelChipText").textContent = p ? p.label : id;
  }

  function renderPlanners() {
    const seg = $("#plannerSeg");
    if (!state.status) return;
    seg.replaceChildren();
    for (const id of ["auto", "gemini", "ollama", "rules"]) {
      const p = plannerById(id);
      const available = id === "auto" || (p && p.available);
      const label = t("modes")[id] + (available ? "" : ` (${t("unavailable")})`);
      seg.append(h("button", { type: "button", role: "radio", "aria-checked": String(state.mode === id), disabled: !available,
        onclick: () => { state.mode = id; renderPlanners(); renderModelChip(); } }, label));
    }
    const resolved = plannerById(state.status.resolved_auto);
    $("#plannerHint").textContent = t("modeHint")[state.mode](resolved ? resolved.label : "rules");
  }

  // ------------------------------------------------------------------ step 1
  function renderIssues() {
    const grid = $("#issueGrid");
    grid.replaceChildren();
    for (const s of state.samples) {
      const active = state.dataset && state.dataset.name === `${s.id}.csv`;
      grid.append(h("button", { type: "button", class: "issue", role: "listitem", "aria-pressed": String(!!active),
        onclick: () => loadSample(s.id), disabled: state.busy },
      h("span", { class: "ico", svg: ICONS[s.issue] ? s.issue : "custom" }),
      h("span", {}, h("span", { class: "t", text: t("issues")[s.issue] || s.title }), h("br"),
        h("span", { class: "d", text: state.lang === "hi" && s.title_hi ? s.title_hi : s.description }))));
    }
  }

  async function loadSample(id) {
    if (state.busy) return;
    state.busy = true;
    setStatus("#s1status", t("loading"));
    try {
      const ds = await api("/api/datasets/sample", { method: "POST", body: JSON.stringify({ sample_id: id }) });
      onDataset(ds);
    } catch (e) {
      setStatus("#s1status", e.message, true);
    } finally {
      state.busy = false;
      renderIssues();
    }
  }

  async function uploadFile(file) {
    if (!file) return;
    const mb = state.status ? state.status.limits.max_upload_mb : 5;
    if (!/\.(csv|xlsx)$/i.test(file.name)) return setStatus("#s1status", t("fileType"), true);
    if (file.size > mb * 1024 * 1024) return setStatus("#s1status", t("fileTooBig")(mb), true);
    state.busy = true;
    setStatus("#s1status", t("loading"));
    const form = new FormData();
    form.append("file", file);
    try {
      onDataset(await api("/api/datasets/upload", { method: "POST", body: form }));
    } catch (e) {
      setStatus("#s1status", e.message, true);
    } finally {
      state.busy = false;
      $("#fileInput").value = "";
    }
  }

  function onDataset(ds) {
    state.dataset = ds;
    state.result = null;
    state.maxStep = 1;
    state.plotted = false;
    setStatus("#s1status", t("loaded")(ds.profile.title));
    $("#toStep2").disabled = false;
    renderDataset();
    renderIssues();
    renderExamples();
    renderSteps();
  }

  function sevIcon(sev) { return h("span", { class: `sev ${sev}`, svg: sev === "warning" ? "warning" : sev === "blocking" ? "blocking" : sev === "ok" ? "check" : "info" }); }

  function table(rows, columns, opts = {}) {
    if (!rows || !rows.length) return h("p", { class: "muted small", text: "-" });
    const cols = columns || Object.keys(rows[0]);
    return h("div", { class: "table-wrap", style: opts.maxHeight ? `max-height:${opts.maxHeight}px` : null },
      h("table", {},
        h("thead", {}, h("tr", {}, cols.map((c) => h("th", { scope: "col", class: rows.some((r) => typeof r[c] === "number") ? "num" : null, text: c })))),
        h("tbody", {}, rows.map((r) => h("tr", {}, cols.map((c) => {
          const v = r[c];
          const isNull = v === null || v === undefined;
          return h("td", { class: isNull ? "null" : typeof v === "number" ? "num" : null, text: isNull ? "blank" : fmtCell(v) });
        }))))));
  }

  function renderDataset() {
    const ds = state.dataset;
    const view = $("#datasetView");
    if (!ds) { view.hidden = true; return; }
    const p = ds.profile, hs = ds.health.summary;
    const src = p.sources_in_data.map((s) => t("source")[s] || s).join(", ");
    const colRows = Object.values(p.columns).map((c) => ({ column: c.name, [t("role")]: c.role, [t("unit")]: c.unit || "", [t("missing")]: c.missing }));
    view.replaceChildren(
      h("div", { class: "card" },
        h("div", { class: "row-between" },
          h("div", {}, h("h2", { text: state.lang === "hi" && p.title_hi ? p.title_hi : p.title }), h("div", { class: "muted small mono", text: ds.name })),
          h("span", { class: "badge " + (p.source === "official" ? "ok" : "info"), text: src })),
        p.description ? h("p", { class: "muted small", text: p.description }) : null,
        h("div", { class: "stats" },
          [[t("rows"), hs.rows], [t("columns"), hs.columns], [t("months"), hs.periods ? `${hs.periods}: ${hs.first_period}…${hs.last_period}` : "0"], [t("entities"), hs.entities]]
            .map(([k, v]) => h("div", { class: "stat" }, h("div", { class: "k", text: k }), h("div", { class: "v", text: String(v) }))))),
      h("div", { class: "grid-2" },
        h("div", { class: "card" }, h("h3", { text: t("health") }),
          h("ul", { class: "issues" }, ds.health.issues.map((i) => h("li", {}, sevIcon(i.severity), h("span", { class: "small", text: i.message }))))),
        h("div", { class: "card" }, h("h3", { text: t("columnsTitle") }), table(colRows, null, { maxHeight: 260 }))),
      h("details", { class: "card" }, h("summary", { text: t("preview") }), h("div", { style: "margin-top:10px" }, table(ds.preview))),
    );
    view.hidden = false;
  }

  // ------------------------------------------------------------------ step 2
  function renderExamples() {
    const box = $("#examples");
    box.replaceChildren();
    const ex = state.dataset?.profile.examples || {};
    const list = ex[state.lang] && ex[state.lang].length ? ex[state.lang] : ex.en || [];
    for (const q of list) {
      box.append(h("button", { type: "button", lang: /[ऀ-ॿ]/.test(q) ? "hi" : "en", onclick: () => { $("#question").value = q; $("#question").focus(); } }, q));
    }
    if (list.length) $("#question").placeholder = list[0];
  }

  async function ask() {
    if (state.busy) return;
    const q = $("#question").value.trim();
    if (q.length < 2) return setStatus("#s2status", t("askEmpty"), true);
    state.busy = true;
    const btn = $("#askBtn");
    btn.disabled = true;
    btn.replaceChildren(h("span", { class: "spinner", "aria-hidden": "true" }), h("span", { text: t("calculating") }));
    setStatus("#s2status", "");
    try {
      const res = await api("/api/ask", { method: "POST", body: JSON.stringify({ dataset_id: state.dataset.id, question: q, lang: state.lang, mode: state.mode }) });
      state.result = res;
      state.plotted = false;
      state.maxStep = 3;
      renderCalc();
      renderAnswer();
      renderCaveats();
      goTo(3);
    } catch (e) {
      setStatus("#s2status", e.status === 400 && /not found/i.test(e.message) ? t("reloadData") : e.message, true);
    } finally {
      state.busy = false;
      btn.disabled = false;
      btn.replaceChildren(t("ask"));
    }
  }

  // ------------------------------------------------------------------ step 3
  function renderCalc() {
    const r = state.result, view = $("#calcView");
    if (!r) return;
    const plan = r.plan, calc = r.calculation;
    const planCard = h("div", { class: "card" },
      h("dl", { class: "kv" },
        h("dt", { text: t("readBy") }), h("dd", {}, plan.planner_label, plan.model && plan.planner !== "rules" ? h("span", { class: "muted mono small", text: `  ${plan.model}` }) : null),
        plan.latency_ms ? [h("dt", { text: t("time") }), h("dd", { text: `${plan.latency_ms} ${t("ms")}` })] : null),
      h("h3", { style: "margin-top:14px", text: t("toolCall") }),
      h("pre", { class: "code", text: JSON.stringify({ tool: plan.tool, arguments: plan.args }, null, 2) }),
      plan.first_attempt ? [h("p", { class: "small", style: "margin-top:12px", text: t("firstAttempt") }),
        h("pre", { class: "code", text: JSON.stringify({ tool: plan.first_attempt.tool, arguments: plan.first_attempt.args }, null, 2) })] : null);

    if (!calc) {
      view.replaceChildren(planCard, h("div", { class: "card" }, h("ul", { class: "issues" },
        h("li", {}, sevIcon("blocking"), h("span", { text: t("noCalc") })))));
      return;
    }
    const cc = calc.cross_check || {};
    const ev = calc.evidence;
    const period = calc.period.start ? (calc.period.start === calc.period.end ? calc.period.start : `${calc.period.start} to ${calc.period.end}`) : "-";
    view.replaceChildren(
      planCard,
      h("div", { class: "card" },
        h("div", { class: "row-between" }, h("h3", { text: t("sql") }),
          h("span", { class: "badge " + (cc.match ? "ok" : "danger") }, h("span", { svg: cc.match ? "check" : "blocking", style: "width:12px;height:12px;display:inline-flex" }),
            cc.match ? t("crossOk")(cc.compared) : t("crossFail"))),
        h("pre", { class: "code", text: calc.sql }),
        h("dl", { class: "kv", style: "margin-top:12px" },
          h("dt", { text: t("method") }), h("dd", { class: "mono small", text: calc.method }),
          h("dt", { text: t("period") }), h("dd", { class: "mono small", text: period }))),
      h("div", { class: "stats" },
        [[t("rowsUsed"), calc.rows_used], [t("rowsSkipped"), calc.rows_skipped], [t("evidence"), ev.total], [t("toolCall"), calc.tool]]
          .map(([k, v]) => h("div", { class: "stat" }, h("div", { class: "k", text: k }), h("div", { class: "v", text: String(v) })))),
      h("details", { class: "card" }, h("summary", { text: t("evidence") }),
        h("p", { class: "muted small", style: "margin-top:8px", text: t("showing")(ev.shown, ev.total) }), table(ev.rows, null, { maxHeight: 360 })),
    );
  }

  // ------------------------------------------------------------------ step 4
  function confidenceBadge(c) {
    const cls = c.level === "verified" ? "ok" : c.level === "partial" ? "warn" : "danger";
    return h("span", { class: `badge ${cls}`, text: c.label });
  }

  function renderAnswer() {
    const r = state.result, view = $("#answerView");
    if (!r) return;
    const a = r.answer;
    const refused = r.status !== "answered";
    const nodes = [
      h("div", { class: "answer-box" + (refused ? " refused" : "") },
        h("div", { class: "row-between", style: "margin-bottom:6px" }, h("span", { class: "muted small", text: r.question }), confidenceBadge(r.confidence)),
        h("p", { class: "answer-text", lang: r.lang, text: a.text }),
        refused ? null : h("p", { class: "muted small", text: a.narration && a.narration.used ? t("narrUsed") : t("narrNot") })),
    ];
    if (r.chart) nodes.push(h("div", { class: "card" }, h("div", { id: "chart", class: "chart", role: "img", "aria-label": a.text })));
    if (a.table && a.table.length) nodes.push(h("details", { class: "card" }, h("summary", { text: t("resultTable") }), h("div", { style: "margin-top:10px" }, table(a.table))));
    view.replaceChildren(...nodes);
  }

  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  function drawChart() {
    const r = state.result;
    const el = $("#chart");
    if (!r || !r.chart || !el || !window.Plotly) return;
    const c = r.chart;
    const accent = cssVar("--accent"), muted = cssVar("--bar-muted"), warn = cssVar("--warn"), text = cssVar("--text"), grid = cssVar("--grid"), sub = cssVar("--muted");
    const data = c.data.map((tr) => {
      const out = { ...tr };
      delete out.highlight; delete out.flagged;
      if (tr.type === "bar") {
        out.marker = { color: (tr.highlight || []).map((hl) => (hl ? accent : muted)) };
        out.textfont = { color: text };
        out.textposition = "outside";
        out.cliponaxis = false;
      } else {
        out.line = { color: accent, width: 3 };
        out.marker = { size: (tr.flagged || []).map((f) => (f ? 12 : 7)), color: (tr.flagged || []).map((f) => (f ? warn : accent)) };
      }
      return out;
    });
    const layout = {
      ...c.layout,
      title: { ...(c.layout.title || {}), x: 0, xanchor: "left", font: { size: 14, color: sub } },
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: getComputedStyle(document.body).fontFamily, color: text, size: 13 },
      margin: { l: 10, r: 24, t: 40, b: 50 }, showlegend: false, bargap: 0.3,
      xaxis: { ...(c.layout.xaxis || {}), gridcolor: grid, zerolinecolor: grid, automargin: true, title: { ...((c.layout.xaxis || {}).title || {}), font: { size: 12, color: sub } } },
      yaxis: { ...(c.layout.yaxis || {}), gridcolor: grid, zerolinecolor: grid, automargin: true, title: { ...((c.layout.yaxis || {}).title || {}), font: { size: 12, color: sub } } },
    };
    const tr = c.data[0];
    if (tr.type === "scatter" && tr.flagged) {
      layout.annotations = tr.flagged.map((f, i) => f ? { x: tr.x[i], y: tr.y[i], text: state.lang === "hi" ? "रीडिंग जांचें" : "Check reading",
        showarrow: true, arrowhead: 0, ax: 0, ay: -28, font: { size: 12, color: warn } } : null).filter(Boolean);
    }
    if (tr.type === "bar" && tr.orientation === "h") layout.yaxis.ticksuffix = "  ";
    window.Plotly.react(el, data, layout, { displayModeBar: false, responsive: true });
    state.plotted = true;
  }

  // ------------------------------------------------------------------ step 5
  function renderCaveats() {
    const r = state.result, view = $("#caveatView");
    if (!r) return;
    const items = r.caveats || [];
    const problems = items.filter((c) => c.severity !== "info");
    view.replaceChildren(
      h("div", { class: "card" },
        h("div", { class: "row-between", style: "margin-bottom:10px" }, h("h3", { style: "margin:0", text: t("confidence") }), confidenceBadge(r.confidence)),
        problems.length ? null : h("p", { class: "small", text: t("noCaveats") }),
        h("ul", { class: "issues" }, items.map((c) => h("li", {}, sevIcon(c.severity),
          h("div", {}, h("div", { class: "small", style: "font-weight:600", text: t("sev")[c.severity] || c.severity }),
            h("div", { class: "small", lang: r.lang, text: c.message })))))),
      r.calculation ? h("div", { class: "card" }, h("dl", { class: "kv" },
        h("dt", { text: t("method") }), h("dd", { class: "mono small", text: r.calculation.method }),
        h("dt", { text: t("rowsUsed") }), h("dd", { text: String(r.calculation.rows_used) }),
        h("dt", { text: t("rowsSkipped") }), h("dd", { text: String(r.calculation.rows_skipped) }))) : null,
    );
  }

  async function loadAudit() {
    const view = $("#auditView");
    try {
      const rows = await api("/api/audit?limit=10");
      if (!rows.length) return view.replaceChildren(h("p", { class: "muted", text: t("auditEmpty") }));
      view.replaceChildren(h("div", { style: "margin-top:10px" }, table(rows.map((x) => ({
        [t("when")]: x.ts.replace("T", " ").slice(0, 19), [t("question")]: x.question, [t("tool")]: x.tool, [t("confidence")]: x.confidence,
      })))));
    } catch (e) {
      view.replaceChildren(h("p", { class: "error", text: e.message }));
    }
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    for (const b of $$(".topbar .seg button")) b.addEventListener("click", () => { state.lang = b.dataset.lang; applyLang(); });
    $("#toStep2").addEventListener("click", () => { if (!state.dataset) return; unlock(2); goTo(2); });
    $("#askBtn").addEventListener("click", ask);
    $("#question").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); ask(); } });
    for (const b of $$("[data-goto]")) b.addEventListener("click", () => goTo(Number(b.dataset.goto)));
    for (const b of $$("[data-next]")) b.addEventListener("click", () => { const n = Number(b.dataset.next); unlock(n); goTo(n); });
    $("#askAnother").addEventListener("click", () => { state.maxStep = 2; $("#question").value = ""; goTo(2); $("#question").focus(); });
    $("#changeData").addEventListener("click", () => goTo(1));
    $("#auditBox").addEventListener("toggle", () => { if ($("#auditBox").open) loadAudit(); });
    $("#fileInput").addEventListener("change", (e) => uploadFile(e.target.files[0]));
    const dz = $("#dropZone");
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
    dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("drag"); uploadFile(e.dataTransfer.files[0]); });
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", () => { if (state.step === 4) drawChart(); });
  }

  async function init() {
    wire();
    renderSteps();
    try {
      const [status, samples] = await Promise.all([api("/api/status"), api("/api/samples")]);
      state.status = status;
      state.samples = samples;
      state.mode = status.default_mode || "auto";
      $("#versionText").textContent = `v${status.version}`;
    } catch (e) {
      setStatus("#s1status", e.message, true);
    }
    applyLang();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
