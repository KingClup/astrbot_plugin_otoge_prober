"use strict";
/* 传分网站（SDVX / 音击）。全部用 DOM 接口拼页面（不用 innerHTML），CSP 只允许本站脚本。 */
(function () {
  const $ = (id) => document.getElementById(id);
  // 看板娘图片取不到（公开版包里没有这些图）：这张图不占地方，顶栏也不给它留位置
  (function () {
    function isGirl(t) { return t && t.tagName === "IMG" && /\/img\/yume-/.test(t.getAttribute("src") || ""); }
    function mark(t, missing) {
      t.classList.toggle("girl-missing", missing);
      if (t.id === "heroGirl") document.body.classList.toggle("no-hero-girl", missing);
    }
    document.addEventListener("error", function (e) { if (isGirl(e.target)) mark(e.target, true); }, true);
    document.addEventListener("load", function (e) { if (isGirl(e.target)) mark(e.target, false); }, true);
    var imgs = document.querySelectorAll('img[src^="/img/yume-"]');
    for (var i = 0; i < imgs.length; i++) if (imgs[i].complete && imgs[i].naturalWidth === 0) mark(imgs[i], true);
  })();
  const S = {
    game: "sdvx", view: "find", me: null, cats: {}, idx: {}, scores: {}, summary: {},
    hits: null, query: "", shown: 50, sheet: null, mineLevel: {}, saves: 0, batch: null, showConst: false,
  };
  const SDVX_LAMPS = [["PLAY", "PLAYED"], ["COMP", "COMP"], ["EXC", "EX COMP"], ["MXV", "MAXXIVE"], ["UC", "UC"], ["PUC", "PUC"]];
  const LAMP_RANK = { PLAY: 0, COMP: 1, EXC: 2, MXV: 3, UC: 4, PUC: 5 };
  const LAMP_COEF = { PLAY: 50, COMP: 100, EXC: 102, MXV: 104, UC: 106, PUC: 110 };
  const GRADES = [[9900000, "S", 105], [9800000, "AAA+", 102], [9700000, "AAA", 100], [9500000, "AA+", 97],
    [9300000, "AA", 94], [9000000, "A+", 91], [8700000, "A", 88], [8000000, "B", 85], [7000000, "C", 82], [0, "D", 80]];
  const GEKI_RANKS = [[1007500, "SSS+"], [1000000, "SSS"], [990000, "SS"], [970000, "S"], [940000, "AAA"], [900000, "AA"],
    [850000, "A"], [800000, "BBB"], [750000, "BB"], [700000, "B"], [500000, "C"], [0, "D"]];
  const CLASS_COLOR = { SIENNA: "#d0743f", COBALT: "#3d6fe6", DANDELION: "#e8b81e", CYAN: "#22b8d2", SCARLET: "#e2324a",
    CORAL: "#f77ea0", ARGENTO: "#9aa6b8", ELDORA: "#d9a21f", CRIMSON: "#b0102c", IMPERIAL: "#8c4ef0" };
  function classTag(name) {
    const [base, roman] = String(name || "").split(" ");
    const n = { I: 1, II: 2, III: 3, IV: 4 }[roman] || 1;
    const el = h("span", { class: "cls", text: base + " " + "★".repeat(n) + "☆".repeat(4 - n) });
    el.style.color = CLASS_COLOR[base] || "";
    return el;
  }
  const SDVX_SPECIAL = ["INF", "GRV", "HVN", "VVD", "XCD", "NBL", "ULT"];
  const SDVX_MAX = 10000000, GEKI_MAX = 1010000;

  // ---------- 小工具 ----------
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
        else if (k === "data") Object.entries(v).forEach(([dk, dv]) => (el.dataset[dk] = dv));
        else el.setAttribute(k, v === true ? "" : v);
      }
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const comma = (n) => Number(n).toLocaleString("en-US");
  // SDVX 分数照机台的样子：补满 8 位，前 4 位大、后 4 位小，前面补的 0 变暗（9,912,345 → 0991 2345）
  function sdvxDigits(n, cls) {
    const s8 = String(Math.max(0, Math.min(Math.floor(Number(n) || 0), 99999999))).padStart(8, "0");
    let lead = s8.length - s8.replace(/^0+/, "").length;
    if (lead === 8) lead = 7;
    const el = h("span", { class: "sdsc" + (cls ? " " + cls : ""), title: comma(n) });
    const hi = h("span", { class: "hi" }), lo = h("span", { class: "lo" });
    for (let i = 0; i < 8; i++) (i < 4 ? hi : lo).append(h("span", { class: i < lead ? "z" : undefined, text: s8[i] }));
    el.append(hi, lo);
    return el;
  }
  // 附加分数开关（SDVX EX SCORE / 音击白金分）：登录了就存到 bot 那边，VF 50 / B50 图也跟着
  const EXTRA_KEY = { sdvx: "sdvx_ex", geki: "geki_plat" };
  function showExtra(g) {
    const k = EXTRA_KEY[g];
    if (S.me && S.me.show && k in S.me.show) return !!S.me.show[k];
    return store.get("sb_show_" + k) !== "0";
  }
  function extraTxt(g, rec) {
    if (!rec || !showExtra(g)) return "";
    if (g === "sdvx" && rec.x) return " EX " + comma(rec.x);
    if (g === "geki" && rec.p) return " P " + comma(rec.p);
    return "";
  }
  const scoreEl = (g, n, cls) => (g === "sdvx" ? sdvxDigits(n, cls) : h("span", { class: cls, text: comma(n) }));
  // 曲绘：服务器从 sdvx.in 拿了缩成 160px 缓存；滚到才加载，拿不到就留渐变底
  function jacket(game, songKey, size, lazy) {
    const img = h("img", { alt: "", loading: lazy ? "lazy" : undefined, decoding: "async", src: "/api/sb/jk/" + game + "/" + encodeURIComponent(songKey) + ".jpg?v=2" });
    img.addEventListener("load", () => img.classList.add("ok"));
    img.addEventListener("error", () => img.remove());
    return h("div", { class: "jk s" + size }, img);
  }
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 无痕模式 */ } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* 无痕模式 */ } },
  };
  // SDVX 单曲 VF ×50 显示（0.403 → 20.15），50 张平均 = 总 VF，和中二 / 舞萌的单曲 rating 一个看法
  const fs = (k) => { const v = k * 5; return Math.floor(v / 100) + "." + String(v % 100).padStart(2, "0"); };
  const fk = (k) => (k < 0 ? "-" : "") + Math.floor(Math.abs(k) / 1000) + "." + String(Math.abs(k) % 1000).padStart(3, "0");
  let toastTimer = 0;
  function toast(msg, yay) {                              // yay：传好了——看板娘比个耶
    const t = $("toast");
    t.hidden = true; void t.offsetWidth;                 // 连着弹两次也重新演一遍
    t.replaceChildren();
    t.classList.toggle("yay", !!yay);
    if (yay) t.append(h("img", { class: "toast-girl", src: "/img/yume-peace.webp", alt: "", width: 520, height: 385 }));
    t.append(h("span", { text: msg }));
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), yay ? 3400 : 2600);
  }
  async function api(path, body) {
    const opt = { credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      opt.method = "POST";
      opt.headers["Content-Type"] = "application/json";
      opt.headers["X-SB"] = "1";
      opt.body = JSON.stringify(body);
    }
    let r;
    try { r = await fetch(path, opt); }                   // 断网 / 页面被切到后台时请求会直接失败：当成「没连上」，别让调用的地方崩掉
    catch (e) { return { _status: 0, offline: true }; }
    let js = {};
    try { js = await r.json(); } catch (e) { /* 非 JSON */ }
    js._status = r.status;
    return js;
  }
  function fold(s) {
    s = (s || "").normalize("NFKC").toLowerCase();
    s = s.replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60));
    return s.replace(/[\s\-_~〜～・.,，。、'"`!！?？:：;；/／\\()（）\[\]【】「」『』<>《》♪☆★○●◇◆□■△▽♡♥†※#＊*+＋=＝|｜…·•]+/g, "");
  }
  // 音击「详细定数」开关：12 以上、有定数的谱面把等级换成定数（14+ → 14.7）
  function lvLabel(c, g) {
    if (g === "geki" && S.showConst && !c.q && c.n && levelNum(c.l) >= 12) return c.n.toFixed(1);
    return c.l;
  }
  const levelNum = (l) => { const m = String(l).match(/(\d+(?:\.\d+)?)(\+)?/); return m ? parseFloat(m[1]) + (m[2] ? 0.5 : 0) : 0; };

  // ---------- 分数 / VF ----------
  function grade(score) { for (const g of GRADES) if (score >= g[0]) return g; return GRADES[GRADES.length - 1]; }
  function sdvxVf(level, score, lamp) {
    if (!score || !(lamp in LAMP_COEF)) return 0;
    const lv10 = Math.round(level * 10);
    const x = lv10 * 2 * Math.min(score, SDVX_MAX) * grade(score)[2] * LAMP_COEF[lamp];
    return (x - (x % 1e11)) / 1e11;
  }
  function gekiRank(score) { for (const r of GEKI_RANKS) if (score >= r[0]) return r[1]; return "D"; }
  function gekiScorePart(cst, score) {
    const c = Math.round(cst * 1000);
    const P = [[1010000, 2000], [1007500, 1750], [1000000, 1250], [990000, 750], [970000, 0], [900000, -4000], [800000, -6000]];
    if (score >= P[0][0]) return c + P[0][1];
    for (let i = 0; i + 1 < P.length; i++) {
      const [hi, hv] = P[i], [lo, lv] = P[i + 1];
      if (lo <= score && score < hi) return Math.max(c + lv + Math.floor(((hv - lv) * (score - lo)) / (hi - lo)), 0);
    }
    if (score < 500000) return 0;
    return Math.max(Math.floor(((c - 6000) * (score - 500000)) / 300000), 0);
  }
  function gekiRate(cst, score, lamp, fb) {
    const sb = score >= 1007500 ? 300 : score >= 1000000 ? 200 : score >= 990000 ? 100 : 0;
    const lb = lamp === "AB" ? (score >= GEKI_MAX ? 350 : 300) : lamp === "FC" ? 100 : 0;
    return gekiScorePart(cst, score) + sb + lb + (fb ? 50 : 0);
  }
  function starsOf(plat, max) {
    if (!max || !plat) return 0;
    const pct = (plat * 100) / max;
    for (const [b, s] of [[98, 5], [97, 4], [96, 3], [95, 2], [94, 1]]) if (pct >= b) return s;
    return 0;
  }
  function psRate(cst, stars) { const s = Math.max(0, Math.min(stars, 5)); const c10 = Math.round(cst * 10); return Math.floor((s * c10 * c10) / 100); }
  function lampClass(game, rec) {
    if (!rec) return "";
    if (game === "sdvx") return "L-" + rec.l;
    if (rec.l === "AB") return rec.s >= GEKI_MAX ? "L-ABP" : "L-AB";
    return rec.l === "FC" ? "L-FC" : "L-NONE";
  }
  function lampText(game, rec) {
    if (!rec) return "";
    if (game === "sdvx") return rec.l === "PLAY" ? "PLAYED" : rec.l;
    return (rec.l === "AB" && rec.s >= GEKI_MAX ? "AB+" : rec.l || "") + (rec.fb ? " FB" : "");
  }

  // ---------- 曲库 ----------
  async function loadCatalog(game) {
    if (S.cats[game]) return;
    $("count").textContent = "正在加载曲库…";
    const d = await api("/api/sb/catalog?game=" + game);
    if (!d.songs) { $("count").textContent = "曲库加载失败，刷新页面再试"; return; }
    const songs = d.songs.map((s) => ({ ...s, f: fold(s.t), charts: s.c.map((c) => ({ ...c, key: s.k + ":" + c.d, song: s })) }));
    const byKey = {}, chartByKey = {};
    songs.forEach((s) => { byKey[s.k] = s; s.charts.forEach((c) => (chartByKey[c.key] = c)); });
    S.cats[game] = d;
    S.idx[game] = { songs, byKey, chartByKey };
  }
  async function loadScores(game) {
    if (!S.me || !S.me.login) { S.scores[game] = {}; S.summary[game] = null; return; }
    const d = await api("/api/sb/scores?game=" + game);
    if (d._status === 401) { S.me.login = false; S.scores[game] = {}; S.summary[game] = null; showGuest(); return; }
    S.scores[game] = d.scores || {};
    S.summary[game] = d.summary || null;
  }

  // ---------- 顶栏 ----------
  // 顶栏的看板娘：按游戏、有没有成绩换姿势（别到处都是同一张）
  const HERO_GIRL = {
    sdvx: { some: ["pass", 520, 385], none: ["think", 520, 397] },
    geki: { some: ["ok", 520, 388], none: ["wave", 640, 788] },
  };
  function heroGirl(game, has) {
    const img = $("heroGirl");
    const [name, w, hh] = (HERO_GIRL[game] || HERO_GIRL.sdvx)[has ? "some" : "none"];
    if (img.dataset.pose === name) return;
    img.dataset.pose = name;
    img.width = w; img.height = hh;
    img.classList.toggle("tall", hh > w);          // 全身那两张从头往下露，别的贴底
    img.src = "/img/yume-" + name + ".webp";
  }
  function renderSum() {
    const el = $("sum");
    el.replaceChildren();
    if (!S.me || !S.me.login) return;
    const sm = S.summary[S.game];
    heroGirl(S.game, !!(sm && sm.count));
    const who = h("span", { class: "who", text: S.me.name || "QQ " + S.me.qq });
    if (!sm || !sm.count) {
      el.append(h("div", { class: "hl" }, who, h("span", { class: "lab", text: S.game === "sdvx" ? "VOLFORCE" : "RATING" })),
        h("div", { class: "hn none" }, h("span", { class: "big", text: "还没传" }), h("span", { class: "tip", text: "点歌的难度就能传" })));
      fixBarHeight(); return;
    }
    const count = h("span", { text: "已传 " + sm.count + " 张" });
    if (S.game === "sdvx") {
      const big = h("span", { class: "big", text: sm.total_text });
      big.style.color = CLASS_COLOR[String(sm.class || "").split(" ")[0]] || "";
      el.append(h("div", { class: "hl" }, who, h("span", { class: "lab", text: "VOLFORCE" }), count), h("div", { class: "hn" }, big, classTag(sm.class)));
    } else {
      el.append(h("div", { class: "hl" }, who, h("span", { class: "lab", text: "RATING" }), count), h("div", { class: "hn" }, h("span", { class: "big", text: sm.total_text })));
    }
    fixBarHeight();
  }
  // 搜索框吸在顶栏下面：顶栏高度会变（有没有成绩那一行），量一下
  function fixBarHeight() {
    requestAnimationFrame(() => document.documentElement.style.setProperty("--bar-h", $("sum").closest(".bar").offsetHeight + "px"));
  }
  // 顶栏高度变了（成绩那一块放大 / 收起、换游戏）就重新量，搜索框跟着它
  if (window.ResizeObserver) new ResizeObserver(fixBarHeight).observe($("sum").closest(".bar"));
  // 往下翻：成绩那一块收成一小条；回到顶上再展开。两个门槛错开，页面太短就不收（不然会来回跳）
  let compact = false;
  function onScroll() {
    const y = window.scrollY || 0;
    const room = document.documentElement.scrollHeight - window.innerHeight;
    const next = compact ? y > 24 : (y > 150 && room > 420);
    if (next === compact) return;
    compact = next;
    document.body.classList.toggle("compact", compact);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  function showGuest() { $("guest").hidden = !!(S.me && S.me.login); }

  // ---------- 筛选 ----------
  function opt(v, t) { return h("option", { value: v, text: t }); }
  function buildFilters() {
    const g = S.game, d = S.cats[g], ix = S.idx[g];
    const levels = new Set();
    ix.songs.forEach((s) => s.charts.forEach((c) => levels.add(c.l)));
    const lv = [...levels].filter((l) => l && l !== "?").sort((a, b) => levelNum(a) - levelNum(b) || (a < b ? -1 : 1));
    const fl = $("fLevel"); fl.replaceChildren(opt("", "全部"));
    if (g === "sdvx") {
      const groups = {};
      lv.forEach((l) => { const n = Math.floor(levelNum(l)); (groups[n] = groups[n] || []).push(l); });
      Object.keys(groups).map(Number).sort((a, b) => a - b).forEach((n) => {
        const ls = groups[n];
        if (ls.length === 1 && ls[0] === String(n)) { fl.append(opt("=" + ls[0], ls[0])); return; }
        const og = h("optgroup", { label: "Lv." + n });
        og.append(opt("g" + n, n + " 全部（" + ls.join(" / ").slice(0, 30) + (ls.join(" / ").length > 30 ? "…" : "") + "）"));
        ls.forEach((l) => og.append(opt("=" + l, l)));
        fl.append(og);
      });
    } else {
      lv.forEach((l) => fl.append(opt("=" + l, l)));
    }
    const fd = $("fDiff"); fd.replaceChildren(opt("", "全部"));
    if (g === "sdvx") { ["NOV", "ADV", "EXH", "MXM"].forEach((x) => fd.append(opt(x, x))); fd.append(opt("4TH", "第 4 难度（INF/GRV/HVN/VVD/XCD/NBL）")); }
    else ["BAS", "ADV", "EXP", "MAS", "LUN"].forEach((x) => fd.append(opt(x, x)));
    const fv = $("fVer"); fv.replaceChildren(opt("", "全部"));
    d.versions.slice().reverse().forEach(([code, name]) => fv.append(opt("v" + code, name)));
    if (g === "sdvx") fv.append(opt("gone", "已删除的谱面"));
    const fg = $("fGenre"); fg.replaceChildren(opt("", "全部"));
    (d.genres || []).forEach((x) => fg.append(opt(x, x)));
    $("fGenreBox").hidden = !(d.genres || []).length;
    const fs = $("fState"); fs.replaceChildren(opt("", "全部"), opt("none", "没传过"), opt("done", "传过的"),
      opt("notmax", g === "sdvx" ? "还没 PUC" : "还没 AB"), opt("best", g === "sdvx" ? "VF 50 里的" : "rating 里的"));
    const fo = $("fSort"); fo.replaceChildren(opt("new", "新歌在前"), opt("lvd", "等级高→低"), opt("lva", "等级低→高"),
      opt("title", "曲名"), opt("recent", "最近传的"));
  }
  const FILTER_IDS = ["fLevel", "fDiff", "fVer", "fGenre", "fState"];
  function markFilters() {
    let n = 0;
    FILTER_IDS.forEach((id) => { const on = !!$(id).value; $(id).classList.toggle("set", on); n += on ? 1 : 0; });
    const sortSet = $("fSort").value && $("fSort").value !== "new";
    $("fSort").classList.toggle("set", !!sortSet);
    $("fToggle").textContent = n ? "筛选 · " + n : "筛选";
    $("fToggle").classList.toggle("on", n > 0);
  }
  function toggleFilters(open) {
    const f = $("filters");
    f.hidden = open === undefined ? !f.hidden : !open;
    $("fToggle").setAttribute("aria-expanded", String(!f.hidden));
  }
  const F = () => ({ level: $("fLevel").value, diff: $("fDiff").value, ver: $("fVer").value, genre: $("fGenre").value,
    state: $("fState").value, sort: $("fSort").value });

  function chartPass(c, f, game) {
    const rec = S.scores[game][c.key];
    if (f.ver === "gone") { if (c.x) return false; }
    else if (game === "sdvx" && !c.x) return false;
    if (f.level) {
      if (f.level[0] === "=" && c.l !== f.level.slice(1)) return false;
      if (f.level[0] === "g" && Math.floor(levelNum(c.l)) !== Number(f.level.slice(1))) return false;
    }
    if (f.diff) {
      if (f.diff === "4TH") { if (!SDVX_SPECIAL.includes(c.d)) return false; }
      else if (c.d !== f.diff) return false;
    }
    if (f.state === "none" && rec) return false;
    if (f.state === "done" && !rec) return false;
    if (f.state === "notmax" && rec && (game === "sdvx" ? rec.l === "PUC" : rec.l === "AB")) return false;
    if (f.state === "best") {
      const sm = S.summary[game];
      if (!sm) return false;
      const inb = game === "sdvx" ? sm.b50.includes(c.key) : [...sm.new, ...sm.best, ...sm.plat].includes(c.key);
      if (!inb) return false;
    }
    return true;
  }
  function chartFilterOn(f) { return !!(f.level || f.diff || f.state || f.ver === "gone"); }

  function filtered() {
    const g = S.game, ix = S.idx[g], f = F();
    let base;
    if (S.hits) base = S.hits.map((x) => ix.byKey[x.k]).filter(Boolean);
    else base = ix.songs.slice();
    const out = [];
    for (const s of base) {
      if (f.ver && f.ver !== "gone" && "v" + s.v !== f.ver) continue;
      if (f.genre && s.g !== f.genre) continue;
      const ok = s.charts.filter((c) => chartPass(c, f, g));
      if (!ok.length) continue;
      out.push({ s, ok });
    }
    if (S.hits && f.sort === "new") return out;          // 搜索结果默认按相关度
    const sc = S.scores[g];
    const maxLv = (o) => Math.max(...o.ok.map((c) => c.n || levelNum(c.l)));
    const recent = (o) => Math.max(0, ...o.s.charts.map((c) => (sc[c.key] ? sc[c.key].t : 0)));
    const ord = {
      new: (a, b) => (g === "sdvx" ? Number(b.s.k) - Number(a.s.k) : (Number(b.s.v) - Number(a.s.v)) || (a.s.t < b.s.t ? -1 : 1)),
      lvd: (a, b) => maxLv(b) - maxLv(a), lva: (a, b) => maxLv(a) - maxLv(b),
      title: (a, b) => a.s.t.localeCompare(b.s.t, "ja"), recent: (a, b) => recent(b) - recent(a),
    }[f.sort] || (() => 0);
    out.sort(ord);
    return out;
  }

  // ---------- 列表 ----------
  function pill(c, game, dim) {
    const rec = S.scores[game][c.key];
    const kids = [h("span", { class: "d", text: c.d }), h("span", { class: "lv", text: lvLabel(c, game) })];
    if (rec) {
      kids.push(scoreEl(game, rec.s, "sc"));
      kids.push(h("i", { class: "lamp " + lampClass(game, rec) }));
    }
    return h("button", { type: "button", class: "pill d-" + c.d + (dim ? " dim" : "") + (c.x ? "" : " gone") + (rec && S.just === c.key ? " just" : ""),
      onclick: () => openSheet(c.song.k, c.d), title: c.d + " " + c.l + (game === "geki" && !c.q && c.n ? "（定数 " + c.n.toFixed(1) + "）" : "") }, kids);
  }
  function renderList() {
    const g = S.game, list = $("list"), f = F();
    list.className = "songs" + (g === "geki" ? " g" : "");
    const rows = filtered();
    const on = chartFilterOn(f);
    $("count").textContent = (S.hits ? "搜到 " : "共 ") + rows.length + " 首" + (S.hits && (on || f.ver || f.genre) ? "（筛选条件也在生效）" : "");
    markFilters();
    list.replaceChildren();
    const vers = Object.fromEntries(S.cats[g].versions);
    let n = 0;
    for (const { s, ok } of rows.slice(0, S.shown)) {
      const hit = S.hits && S.hits.find((x) => x.k === s.k);
      const meta = [h("span", { class: "tag", text: vers[s.v] || s.v || "?" })];
      if (s.g) meta.push(h("span", { class: "tag", text: s.g }));
      if (hit && hit.by) meta.push(h("span", { class: "tag al", text: "外号：" + hit.by }));
      const shownCharts = s.charts.filter((c) => f.ver === "gone" ? !c.x : (g !== "sdvx" || c.x));
      list.append(h("li", { class: "song" },
        jacket(g, s.k, 64, n++ >= 12),
        h("div", { class: "info" }, h("div", { class: "t", text: s.t }), h("div", { class: "a", text: s.a, title: s.a }),
          h("div", { class: "meta" }, meta)),
        h("div", { class: "charts" }, shownCharts.map((c) => pill(c, g, on && !ok.includes(c))))));
    }
    if (!rows.length) {                                   // 一首都没有：看板娘想一想，给个下一步
      list.append(h("li", { class: "empty" },
        h("img", { class: "empty-girl", src: "/img/yume-think.webp", alt: "", width: 520, height: 397 }),
        h("div", { class: "empty-t", text: S.hits ? "没找到这首" : "这个条件下一首都没有" }),
        h("div", { class: "empty-s", text: S.hits ? "换个写法试试：外号、读音、歌名里的几个字都行。" : "把筛选放宽一点，或者点「清除筛选」。" })));
    }
    $("more").hidden = rows.length <= S.shown;
  }

  // 搜索框里打「/sdvx 歌名」「/geki 歌名」「/音击 …」：切游戏再搜
  const GAME_PREFIX = /^[\/／](sdvx|geki|ongeki|音击|オンゲキ)(?:\s+|$)(.*)$/i;
  function gameOf(w) { w = w.toLowerCase(); return w === "sdvx" ? "sdvx" : "geki"; }
  let searchTimer = 0, searchSeq = 0;
  function onSearch() {
    const m = GAME_PREFIX.exec($("q").value.trim());
    if (m) {
      const g = gameOf(m[1]);
      $("q").value = m[2];
      if (g !== S.game) { setGame(g); return; }
    }
    const q = $("q").value.trim();
    $("qx").hidden = !q;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      S.shown = 50;
      if (!q) { S.hits = null; S.query = ""; renderList(); return; }
      const seq = ++searchSeq, g = S.game;
      const d = await api("/api/sb/search?game=" + g + "&q=" + encodeURIComponent(q));
      if (seq !== searchSeq || g !== S.game) return;
      S.hits = d.hits || [];
      // 服务器没搜到时，本地再按读音 / 标题子串兜底
      if (!S.hits.length) {
        const fq = fold(q);
        S.hits = S.idx[g].songs.filter((s) => s.f.includes(fq) || (s.s || []).some((t) => fold(t).includes(fq))).slice(0, 40).map((s) => ({ k: s.k }));
      }
      S.query = q;
      renderList();
    }, 180);
  }

  // ---------- 传分面板 ----------
  function closeSheet() {
    document.body.style.overflow = "";
    $("sheet").hidden = true; $("sheetBg").hidden = true; S.sheet = null;
  }
  function fmtTime(t) { if (!t) return ""; const d = new Date(t * 1000); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }

  function openSheet(songKey, diff) {
    const g = S.game, ix = S.idx[g], s = ix.byKey[songKey];
    if (!s) return;
    const c = s.charts.find((x) => x.d === diff) || s.charts[s.charts.length - 1];
    const rec = S.scores[g][c.key];
    const login = S.me && S.me.login;
    const st = (S.sheet = { song: s, chart: c, lamp: rec ? rec.l : (g === "sdvx" ? "COMP" : ""), fb: !!(rec && rec.fb), stars: rec && rec.st ? rec.st : 0 });
    const vers = Object.fromEntries(S.cats[g].versions);
    const box = $("sheetIn");
    box.replaceChildren();
    box.className = "sheet-in" + (g === "geki" ? " g" : "");

    box.append(h("div", { class: "grab" }),
      h("div", { class: "sheet-head" }, jacket(g, s.k, 88),
        h("div", null, h("h3", { text: s.t }), h("div", { class: "sub", text: [s.a, vers[s.v] || s.v, s.g].filter(Boolean).join(" · ") }))),
      h("div", { class: "difftabs" }, s.charts.filter((x) => g !== "sdvx" || x.x || !c.x).map((x) =>
        h("button", { type: "button", class: "d-" + x.d + (x.d === c.d ? " on" : ""), text: x.d + " " + lvLabel(x, g), onclick: () => openSheet(s.k, x.d) }))));
    let info = c.d + " " + c.l;
    if (g === "geki") info += c.q ? " · 没有定数（不算 rating）" : " · 定数 " + c.n.toFixed(1) + (c.p ? " · P 分满分 " + comma(c.p) : "");
    if (g === "sdvx" && !c.x) info += " · 现行机台已删除";
    if (s.b) info += " · BONUS TRACK 不算 rating";
    box.append(h("div", { class: "old", text: info }));
    if (rec) box.append(h("div", { class: "old" }, "之前：", scoreEl(g, rec.s), " " + lampText(g, rec) + (rec.st ? " ★" + rec.st : "") + (rec.p ? " P " + comma(rec.p) : "") + (rec.x ? " EX " + comma(rec.x) : "") + " · " + fmtTime(rec.t)));

    const max = g === "sdvx" ? SDVX_MAX : GEKI_MAX;
    const sd = g === "sdvx";
    const inp = h("input", { class: "score-in" + (sd ? " sd" : ""), inputmode: "numeric", autocomplete: "off", placeholder: sd ? "" : "如 1,007,321", "aria-label": "分数" });
    if (!login) inp.disabled = true;
    // SDVX：真输入框文字透明，下面垫一层机台样式的 8 位数字，像计算器一样从右边往里推
    const mirror = sd ? h("div", { class: "sd-mirror" }) : null;
    function paint() {
      if (!mirror) return;
      const v = inp.value.replace(/\D/g, "");
      mirror.replaceChildren(sdvxDigits(v || 0, v ? "" : "empty"), h("i", { class: "caret" }));
    }
    inp.addEventListener("input", () => {
      const digits = inp.value.replace(/\D/g, "").replace(/^0+(?=\d)/, "").slice(0, String(max).length);
      const capped = digits ? String(Math.min(Number(digits), max)) : "";
      inp.value = sd ? capped : capped ? comma(capped) : "";
      paint();
      if (g === "sdvx") {
        const v = Number(digits || 0);
        if (v === SDVX_MAX && st.lamp !== "PUC") setLamp("PUC");
        else if (v !== SDVX_MAX && st.lamp === "PUC" && digits) setLamp("UC");
      }
      preview();
    });
    box.append(h("label", { class: "field" }, h("span", { text: sd ? "分数（直接打数字，像机台那样从右边推进来）" : "技术分" }),
      sd ? h("div", { class: "sd-wrap" }, mirror, inp) : inp));
    paint();

    const segBtns = {};
    function setLamp(l) {
      st.lamp = l;
      Object.entries(segBtns).forEach(([k, b]) => b.classList.toggle("on", k === l));
      if (g === "sdvx" && l === "PUC") { inp.value = String(SDVX_MAX); paint(); }
      preview();
    }
    const lamps = g === "sdvx" ? SDVX_LAMPS : [["", "没 FC"], ["FC", "FC"], ["AB", "AB"]];
    const seg = h("div", { class: "seg lamps" }, lamps.map(([k, t]) => (segBtns[k] = h("button", { type: "button", class: "lp L-" + (k || "NONE"), text: t, disabled: !login, onclick: () => setLamp(k) }))));
    box.append(h("div", { class: "field" }, h("span", { text: g === "sdvx" ? "灯（PLAYED = 没过）" : "灯" }), seg));

    let exIn = null;
    if (g === "sdvx") {                         // EX SCORE：可不填，只升不降
      exIn = h("input", { class: "small-in", inputmode: "numeric", autocomplete: "off", placeholder: "EX SCORE（结算画面分数下面那个，可不填）", disabled: !login, "aria-label": "EX SCORE" });
      exIn.addEventListener("input", () => { const dg = exIn.value.replace(/\D/g, "").replace(/^0+(?=\d)/, "").slice(0, 5); exIn.value = dg ? comma(dg) : ""; });
      if (rec && rec.x) exIn.value = comma(rec.x);
      box.append(h("label", { class: "field" }, h("span", { text: "EX SCORE（不算 VF，只是记下来）" }), exIn));
    }
    let platIn = null;
    const starBtns = [];
    if (g === "geki") {
      const fbBtn = h("button", { type: "button", class: "lp L-BELL", text: "FULL BELL", disabled: !login, onclick: () => { st.fb = !st.fb; fbBtn.classList.toggle("on", st.fb); preview(); } });
      fbBtn.classList.toggle("on", st.fb);
      box.append(h("div", { class: "field" }, h("span", { text: "铃" }), h("div", { class: "seg" }, fbBtn)));
      platIn = h("input", { class: "small-in", inputmode: "numeric", placeholder: c.p ? "白金分（满分 " + comma(c.p) + "），填了自动算星" : "白金分", disabled: !login });
      platIn.addEventListener("input", () => {
        const dg = platIn.value.replace(/\D/g, "").slice(0, 5);
        platIn.value = dg ? comma(dg) : "";
        if (dg && c.p) setStars(starsOf(Number(dg), c.p), true);
        preview();
      });
      if (rec && rec.p) platIn.value = comma(rec.p);
      const starsRow = h("div", { class: "seg stars" }, [0, 1, 2, 3, 4, 5, 6].map((n) => {
        const b = h("button", { type: "button", text: n === 0 ? "无" : n === 6 ? "彩★" : "★" + n, disabled: !login, onclick: () => { setStars(n); platIn.value = ""; preview(); } });
        starBtns.push(b); return b;
      }));
      box.append(h("div", { class: "field" }, h("span", { text: "白金分 / 星（算 P 分 50 用，不填也行）" }), platIn, starsRow));
    }
    function setStars(n) { st.stars = n; starBtns.forEach((b, i) => b.classList.toggle("on", i === n)); }
    setStars(st.stars);

    const pv = h("div", { class: "preview" });
    box.append(pv);
    let over = null;
    if (rec && login) {
      over = h("input", { type: "checkbox" });
      over.addEventListener("change", preview);
      box.append(h("label", { class: "check" }, over, "按我填的覆盖（传错了要改低时勾上；平时只保留更高的）"));
    }
    const err = h("div", { class: "err" });
    const saveBtn = h("button", { type: "button", class: "primary", text: login ? "保存" : "登录后才能传分", disabled: !login, onclick: save });
    const row = h("div", { class: "row" }, saveBtn);
    if (rec && login) row.append(h("button", { type: "button", class: "danger", text: "删除这条", onclick: del }));
    box.append(err, row);
    box.append(aliasBox(s));

    function current() {
      const v = Number(inp.value.replace(/\D/g, "") || 0);
      return v;
    }
    function preview() {
      pv.replaceChildren();
      const v = current();
      if (!v) { pv.append(h("span", { text: login ? "填分数后这里显示能拿多少" : "只读模式" })); return; }
      const ov = over && over.checked;
      if (g === "sdvx") {
        let es = v, el = st.lamp;
        if (rec && !ov) { es = Math.max(v, rec.s); if (LAMP_RANK[rec.l] > LAMP_RANK[el]) el = rec.l; }
        const vf = sdvxVf(c.n, es, el);
        const sm = S.summary[g];
        let line = [h("span", null, grade(es)[1] + " · 单曲 "), h("b", { text: fs(vf) })];
        if (sm && c.x) {
          const vals = Object.assign({}, sm.vf); vals[c.key] = vf;
          const top = Object.values(vals).sort((a, b) => b - a).slice(0, 50);
          const total = top.reduce((a, b) => a + b, 0);
          const dlt = total - sm.total;
          const rank = Object.entries(vals).sort((a, b) => b[1] - a[1]).findIndex(([k]) => k === c.key);
          line.push(h("div", null, rank < 50 ? "进 VF 50（第 " + (rank + 1) + " 名）" : "进不了 VF 50（第 50 名是 " + fs(sm.floor) + "）",
            dlt ? h("span", { class: dlt > 0 ? "up" : "down", text: "  总 VF " + (dlt > 0 ? "+" : "") + fk(dlt) }) : "  总 VF 不变"));
        }
        if (rec && !ov && (es !== v || el !== st.lamp)) line.push(h("div", { class: "old" }, "（之前更高的会保留：", scoreEl(g, es), " " + el + "）"));
        pv.append(...line);
      } else {
        if (c.q || s.b) { pv.append(h("span", { text: gekiRank(v) + "（这张不算 rating）" })); return; }
        const es = rec && !ov ? Math.max(v, rec.s) : v;
        const rate = gekiRate(c.n, es, st.lamp || (rec && !ov ? rec.l : ""), st.fb || (rec && !ov && rec.fb));
        pv.append(h("span", null, gekiRank(es) + " · 单曲 "), h("b", { text: fk(rate) }));
        if (st.stars) pv.append(h("div", null, "P 分 ★" + Math.min(st.stars, 5) + " → " + fk(psRate(c.n, st.stars))));
        pv.append(h("div", { class: "old", text: (Number(s.v) >= 150 ? "新曲框（Re:Fresh 起的歌）" : "旧曲框") }));
      }
    }
    async function save() {
      if (!login) return;
      const v = current();
      if (!inp.value) { err.textContent = "先填分数"; inp.focus(); return; }
      if (v > max) { err.textContent = "分数太大了"; return; }
      saveBtn.disabled = true; err.textContent = "";
      const body = { game: g, key: c.key, score: v, lamp: st.lamp, overwrite: !!(over && over.checked) };
      if (exIn && exIn.value) body.ex = Number(exIn.value.replace(/\D/g, ""));
      if (g === "geki") { body.fb = st.fb; body.stars = st.stars; const p = platIn.value.replace(/\D/g, ""); if (p) body.plat = Number(p); }
      const d = await api("/api/sb/score", body);
      saveBtn.disabled = false;
      if (!d.ok) { err.textContent = d.message || "没保存上"; if (d._status === 401) { S.me.login = false; showGuest(); } return; }
      S.scores[g][c.key] = d.record;
      S.summary[g] = d.summary;
      renderSum();
      const dl = d.delta ? "，" + (g === "sdvx" ? "VF " : "rating ") + (d.delta > 0 ? "+" : "") + fk(d.delta) : "";
      toast("已保存：" + s.t + " " + c.d + " " + comma(d.record.s) + (d.kept_higher ? "（保留了之前更高的）" : "") + dl, true);
      closeSheet();
      S.saves += 1;
      S.just = c.key;                                     // 刚传的那张难度块闪一下
      setTimeout(() => { if (S.just === c.key) S.just = null; }, 1600);
      if (S.saves >= 2 && !store.get("sb_batch_tip_off")) $("batchTip").hidden = false;
      if (S.view === "find") { renderList(); const q = $("q"); q.focus(); q.select(); } else renderMine();
    }
    async function del() {
      if (!confirm("删除 " + s.t + " " + c.d + " 的成绩？")) return;
      const d = await api("/api/sb/delete", { game: g, key: c.key });
      if (d.ok) {
        delete S.scores[g][c.key]; S.summary[g] = d.summary; renderSum(); toast("删掉了"); closeSheet();
        S.view === "find" ? renderList() : renderMine();
      }
    }
    if (rec) {
      inp.value = sd ? String(rec.s) : comma(rec.s); paint();
    }
    setLamp(st.lamp);
    preview();
    // 面板里按回车 = 保存（点过灯按钮以后焦点在按钮上也一样）；外号输入框里的回车是加外号
    box.onkeydown = (e) => {
      if (e.key !== "Enter" || e.target.closest(".aliases") || e.isComposing) return;
      e.preventDefault(); save();
    };
    $("sheet").hidden = false; $("sheetBg").hidden = false;
    document.body.style.overflow = "hidden";
    if (login) setTimeout(() => { inp.focus(); inp.select(); }, 60);
  }

  function aliasBox(s) {
    const g = S.game, login = S.me && S.me.login;
    const box = h("div", { class: "aliases" });
    const tags = h("div", { class: "tags" });
    const draw = (al) => { tags.replaceChildren(...(al && al.length ? al.map((a) => h("span", { class: "tag al", text: a })) : [h("span", { class: "old", text: "还没有外号" })])); };
    draw(s.al);
    box.append(h("div", { class: "old", text: "外号（搜歌时能用；SDVX / 音击的 /谱面 也认）" }), tags);
    if (login) {
      const inp = h("input", { class: "small-in", placeholder: "加一个外号", maxlength: "30" });
      const msg = h("div", { class: "err" });
      const add = async () => {
        const a = inp.value.trim();
        if (!a) return;
        const d = await api("/api/sb/alias", { game: g, song: s.k, alias: a });
        msg.textContent = d.message || "";
        if (d.ok) { s.al = d.aliases; draw(s.al); inp.value = ""; }
      };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
      box.append(h("div", { class: "row" }, inp, h("button", { type: "button", class: "ghost", text: "加外号", onclick: add })), msg);
    }
    return box;
  }

  // ---------- 我的成绩 ----------
  function rankRow(g, key, no, value) {
    const c = S.idx[g].chartByKey[key];
    if (!c) return null;
    const rec = S.scores[g][key] || {};
    return h("li", { onclick: () => openSheet(c.song.k, c.d) },
      h("span", { class: "no", text: no }), jacket(g, c.song.k, 40, no > 12),
      h("div", { class: "nm" }, h("div", { text: c.song.t }),
        h("div", null, h("span", { class: "badge d-" + c.d, text: c.d + " " + lvLabel(c, g) }), scoreEl(g, rec.s || 0), " " + lampText(g, rec) + (rec.st ? " ★" + rec.st : ""),
          extraTxt(g, rec) ? h("span", { class: "xs", text: extraTxt(g, rec) }) : null)),
      h("span", { class: "v", text: value }));
  }
  function stat(label, value) { return h("div", { class: "stat" }, h("div", { text: label }), h("div", { text: value })); }
  function levelTiles(g) {
    const ix = S.idx[g];
    const levels = [...new Set(ix.songs.flatMap((s) => s.charts.filter((c) => g !== "sdvx" || c.x).map((c) => c.l)))]
      .filter((l) => levelNum(l) >= (g === "sdvx" ? 14 : 10)).sort((a, b) => levelNum(b) - levelNum(a));
    if (!S.mineLevel[g] || !levels.includes(S.mineLevel[g])) S.mineLevel[g] = levels.find((l) => ix.songs.some((s) => s.charts.some((c) => c.l === l && S.scores[g][c.key]))) || levels[0];
    const sel = h("select", { class: "small-in" }, levels.map((l) => opt(l, "Lv " + l)));
    sel.value = S.mineLevel[g];
    sel.addEventListener("change", () => { S.mineLevel[g] = sel.value; renderMine(); });
    const charts = ix.songs.flatMap((s) => s.charts.filter((c) => c.l === S.mineLevel[g] && (g !== "sdvx" || c.x)));
    const sc = S.scores[g];
    charts.sort((a, b) => (sc[b.key] ? sc[b.key].s : -1) - (sc[a.key] ? sc[a.key].s : -1));
    const done = charts.filter((c) => sc[c.key]).length;
    const legend = g === "sdvx"
      ? [["L-PUC", "PUC"], ["L-UC", "UC"], ["L-MXV", "MAXXIVE"], ["L-EXC", "EX COMP"], ["L-COMP", "COMP"], ["L-PLAY", "PLAYED"]]
      : [["L-ABP", "AB+"], ["L-AB", "AB"], ["L-FC", "FC"], ["L-NONE", "没 FC"]];
    return h("section", { class: "panel" },
      h("h2", null, "等级一览", h("small", { text: "传了 " + done + " / " + charts.length })),
      sel,
      h("div", { class: "legend" }, legend.map(([cl, t]) => h("span", null, h("i", { class: cl }), t))),
      h("div", { class: "tiles" }, charts.map((c) => {
        const rec = sc[c.key];
        return h("button", { type: "button", class: "tile " + (rec ? lampClass(g, rec) : "none"), onclick: () => openSheet(c.song.k, c.d) },
          h("div", { text: c.song.t }), h("div", null, c.d + (rec ? " · " : ""), rec ? scoreEl(g, rec.s) : null));
      })));
  }
  function renderMine() {
    const body = $("mineBody"), g = S.game;
    body.replaceChildren();
    if (!S.me || !S.me.login) { body.append(h("section", { class: "panel" }, "登录以后这里显示你的成绩。回 QQ 发 /传分 拿登录链接。")); return; }
    const sm = S.summary[g];
    if (!sm || !sm.count) { body.append(h("section", { class: "panel" }, "还没传过成绩。去「找歌传分」找到歌，点难度就能传。")); return; }
    const exp = h("a", { href: "/api/sb/export?game=" + g, text: "导出 CSV" });
    if (g === "sdvx") {
      const vals = sm.b50.map((k) => sm.vf[k] || 0);
      const lamps = {};
      Object.values(S.scores[g]).forEach((r) => (lamps[r.l] = (lamps[r.l] || 0) + 1));
      body.append(h("section", { class: "panel" },
        h("h2", null, h("span", null, "VOLFORCE ", (() => { const b = h("span", { text: sm.total_text }); b.style.color = CLASS_COLOR[String(sm.class).split(" ")[0]] || ""; return b; })()),
          h("small", null, classTag(sm.class), " · 已传 " + sm.count + " 张 · ", exp)),
        h("div", { class: "statgrid" },
          stat("单曲最高", vals.length ? fs(Math.max(...vals)) : "-"),
          stat("VF 50 平均", vals.length ? fs(Math.floor(vals.reduce((a, b) => a + b, 0) / vals.length)) : "-"),
          stat("第 50 名", sm.floor ? fs(sm.floor) : "还没满 50"),
          stat("PUC / UC", (lamps.PUC || 0) + " / " + (lamps.UC || 0))),
        h("div", { class: "old", text: "按 ∇ 规则算：每首显示的是单曲 VF ×50（等级 × 分数 × 评级 × 灯），最高 50 张的平均就是 VOLFORCE。QQ 里发 /sdvx b50 出图。" })));
      body.append(h("section", { class: "panel" }, h("h2", null, "VF 50", h("small", { text: sm.b50.length + " 张" })),
        h("ol", { class: "rank" }, sm.b50.map((k, i) => rankRow(g, k, i + 1, fs(sm.vf[k] || 0))))));
    } else {
      const fr = sm.frames;
      body.append(h("section", { class: "panel" },
        h("h2", null, "Rating " + sm.total_text, h("small", null, "已传 " + sm.count + " 张 · ", exp)),
        h("div", { class: "old", text: "Re:Fresh 规则：新曲 10 + 旧曲 50 + P 分 50，合计 ÷ 50。只算你传过的。QQ 里发 /geki b50 手动 出图。" })));
      const sec = (title, keys, kind, fkey) => h("section", { class: "panel" },
        h("h2", null, title, h("small", { text: keys.length + " 张 · +" + fr[fkey].contrib })),
        h("ol", { class: "rank" }, keys.map((k, i) => { const v = sm.vals[k] || {}; return rankRow(g, k, i + 1, fk((kind === "ps" ? v.ps : v.rate) || 0)); })));
      body.append(sec("新曲 10", sm.new, "rate", "new"), sec("旧曲 50", sm.best, "rate", "best"), sec("P 分 50", sm.plat, "ps", "plat"));
    }
    body.append(levelTiles(g));
  }

  // ---------- 切换 ----------
  async function setGame(g) {
    S.game = g; S.hits = null; S.shown = 50; S.batch = null;
    document.body.dataset.game = g;
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", g === "geki" ? "#ffd9e6" : "#101317"));
    $("constBox").hidden = g !== "geki";
    $("extraName").textContent = g === "sdvx" ? "显示 EX SCORE" : "显示白金分";
    $("extraTog").checked = showExtra(g);
    document.querySelectorAll("#games button").forEach((b) => b.classList.toggle("on", b.dataset.game === g));
    store.set("sb_game", g);
    $("bOut").replaceChildren();
    batchIntro();
    $("list").replaceChildren();
    await Promise.all([loadCatalog(g), loadScores(g)]);
    if (!S.idx[g]) return;
    buildFilters();
    renderSum();
    if ($("q").value.trim()) onSearch(); else { renderList(); markFresh(); }
    if (S.view === "mine") renderMine();
    fixBarHeight();
  }
  function setView(v) {
    S.view = v;
    document.querySelectorAll(".views button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
    ["find", "batch", "mine"].forEach((x) => ($(x).hidden = v !== x));
    if (v === "mine") renderMine();
    if (v === "batch") $("bText").focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }

  // ---------- 批量传分 ----------
  const FMT = {
    sdvx: "曲名 | 难度 | 分数 | 灯 | EX SCORE（可不写）\n\n难度  NOV ADV EXH MXM，第 4 难度 INF GRV HVN VVD XCD NBL ULT（写 4TH 也行）\n灯    PUC  UC  MXV(MAXXIVE)  EXC(EX COMP)  COMP  PLAYED(没过)，不写算 COMP",
    geki: "曲名 | 难度 | 技术分 | 灯 | 铃 | 白金分\n\n难度  BAS ADV EXP MAS LUN\n灯    AB  FC  不是就空着或写 -\n铃    FB  不是就空着或写 -\n白金分 有就写数字（自动算星），没有写 - ；也能写 ★4",
  };
  const SAMPLE = {
    sdvx: "VICTIM | MXM | 9,912,345 | UC | 4321\n魔理沙は大変なものを盗んでいきました | EXH | 9,700,000 | EXC\n# 聊天那种空格写法也认：\nvictim exh 9950000 uc",
    geki: "Demonia | MAS | 1,007,321 | AB | FB | 4100\nアイシング・ドリーム | EXP | 1,001,000 | FC | - | -\n# 聊天那种空格写法也认：\ndemonia exp 1008000 ab fb",
  };
  const AI_PROMPT = {
    sdvx: [
      "请帮我从截图里读出 SOUND VOLTEX（ボルテ / SDVX）的成绩，按下面的格式输出。一行一首，只输出这些行，不要表头、不要解释、不要代码块：",
      "曲名 | 难度 | 分数 | 灯 | EX SCORE",
      "",
      "规则：",
      "- 曲名：照截图原样抄（日文 / 英文原文，不要翻译、不要加注音）。",
      "- 难度：NOV / ADV / EXH / MXM / INF / GRV / HVN / VVD / XCD / NBL / ULT 之一（看难度名或颜色：紫 NOV、黄 ADV、红 EXH、白 / 灰 MXM；第 4 难度看不出具体名字就写 4TH）。",
      "- 分数：完整整数，比如 9912345（不是 VF、不是百分比、不要逗号以外的符号）。",
      "- 灯（通关标记）：PUC = PERFECT（满分）、UC = ULTIMATE CHAIN、MXV = MAXXIVE、EXC = EXCESSIVE COMPLETE、COMP = COMPLETE（普通通关）、PLAYED = 没通过 / CRASH。看不出来就写 COMP。",
      "- 截图可能是结果画面、选曲画面、VOLFORCE / VF 50 一览、e-amusement App 的成绩列表，每张图里可能有很多首，全部列出来。",
      "- EX SCORE：截图里有就写整数（如 4321），没有就整栏省略（连同前面的 | 一起不写）。",
      "- 看不清的那一首整行跳过，不要猜，不要编。",
      "",
      "例：",
      "VICTIM | MXM | 9912345 | UC | 4321",
      "魔理沙は大変なものを盗んでいきました | EXH | 9700000 | EXC",
    ].join("\n"),
    geki: [
      "请帮我从截图里读出 オンゲキ（ONGEKI / 音击）的成绩，按下面的格式输出。一行一首，只输出这些行，不要表头、不要解释、不要代码块：",
      "曲名 | 难度 | 技术分 | 灯 | 铃 | 白金分",
      "",
      "规则：",
      "- 曲名：照截图原样抄（日文 / 英文原文，不要翻译）。",
      "- 难度：BAS / ADV / EXP / MAS / LUN 之一（BASIC 绿、ADVANCED 黄、EXPERT 红、MASTER 紫、LUNATIC 白）。",
      "- 技术分（TECHNICAL SCORE）：完整整数，比如 1007321。",
      "- 灯：ALL BREAK 写 AB，FULL COMBO 写 FC，都不是写 -。",
      "- 铃：FULL BELL 写 FB，不是写 -。",
      "- 白金分（PLATINUM SCORE）：截图里有就写整数，没有写 -。",
      "- 截图可能是结果画面、选曲画面、オンゲキ-NET 的成绩列表，每张图里可能有很多首，全部列出来。",
      "- 看不清的那一首整行跳过，不要猜，不要编。",
      "",
      "例：",
      "Demonia | MAS | 1007321 | AB | FB | 4100",
      "アイシング・ドリーム | EXP | 1001000 | FC | - | -",
    ].join("\n"),
  };
  function batchIntro() {
    const g = S.game;
    $("bFmt").textContent = FMT[g];
    $("bText").placeholder = SAMPLE[g].split("\n")[0] + "\n…一行一首";
    $("bCsvWay").hidden = g !== "sdvx";
    $("bChat").textContent = "发「/" + g + " 批量传」，换行后一行一首（格式和这里一样）。传完回你总 " + (g === "sdvx" ? "VF" : "rating") + " 变化和没认出的行。";
  }
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* 退回老办法 */ }
    const ta = h("textarea");
    ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
    ta.value = text; document.body.append(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }
  // 一首歌 + 写的难度 → 谱面（规则和服务器一样：没写 → MXM / MAS；第 4 难度名字写错按这首实际的）
  function chartFor(song, d) {
    const has = (x) => song.charts.find((c) => c.d === x);
    if (!d) return has(S.game === "sdvx" ? "MXM" : "MAS") || (S.game === "geki" && has("LUN")) || song.charts[song.charts.length - 1];
    if (has(d)) return has(d);
    if (S.game === "sdvx" && (d === "4TH" || SDVX_SPECIAL.includes(d))) return song.charts.find((c) => SDVX_SPECIAL.includes(c.d)) || (d === "4TH" ? has("MXM") : null);
    return null;
  }
  async function batchParse() {
    const g = S.game, text = $("bText").value;
    const out = $("bOut");
    if (!text.trim()) { toast("先贴点内容"); return; }
    $("bParse").disabled = true;
    const d = await api("/api/sb/batch", { game: g, text });
    $("bParse").disabled = false;
    if (!d.ok) { toast(d.message || "识别失败"); return; }
    S.batch = d.rows.map((r) => ({ ...r, use: !!r.ok }));
    S.batchCsv = !!d.csv;
    renderBatch();
    out.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function batchStatus(r) {
    if (!r.key) return ["no", "没认出"];
    const g = S.game, old = (S.scores[g] || {})[r.key];
    if (!old) return ["new", "新传"];
    if (r.score > old.s) return ["up", "+" + comma(r.score - old.s)];
    if (r.score === old.s) return ["same", "一样"];
    return ["low", "比之前低"];
  }
  function renderBatch() {
    const g = S.game, out = $("bOut"), rows = S.batch || [];
    out.replaceChildren();
    if (!rows.length) { out.append(h("div", { class: "panel" }, "一行都没认出来。看看格式：曲名 | 难度 | 分数 | 灯")); return; }
    const ix = S.idx[g];
    const list = h("ol", { class: "brows" + (g === "geki" ? " g" : "") });
    const footBtn = h("button", { type: "button", class: "primary" });
    const over = h("input", { type: "checkbox" });
    const sel = () => rows.filter((r) => r.use && r.key);
    const refreshFoot = () => {
      const n = sel().length;
      const login = S.me && S.me.login;
      footBtn.textContent = login ? "传入选中的 " + n + " 条" : "登录后才能传（QQ 发 /传分）";
      footBtn.disabled = !n || !login;
    };
    const SHOW_OK = 150;                       // 官网 CSV 几千行：认出来的只列前 150 行（其余照样会传），没认出的全列
    let shownOk = 0, hiddenOk = 0, ri = 0;
    rows.forEach((r) => {
      if (r.key && shownOk >= SHOW_OK) { hiddenOk += 1; return; }
      if (r.key) shownOk += 1;
      const lazy = ri++ > 20;
      const li = h("li", { class: "brow" + (r.key ? "" : " bad") });
      const draw = () => {
        const [cls, label] = batchStatus(r);
        const cb = h("input", { type: "checkbox", disabled: !r.key, "aria-label": "传这一行" });
        cb.checked = !!(r.use && r.key);
        cb.addEventListener("change", () => { r.use = cb.checked; refreshFoot(); });
        const nm = h("div", { class: "nm" });
        if (r.key) {
          nm.append(h("div", { class: "t", text: r.t }),
            h("div", { class: "s" }, h("span", { class: "badge d-" + r.d, text: r.d + " " + (r.lv || "") }),
              scoreEl(g, r.score), " " + (g === "sdvx" ? (r.lamp || "COMP") + (r.ex ? " EX " + comma(r.ex) : "") : [r.lamp, r.fb ? "FB" : "", r.plat ? "P " + comma(r.plat) : "", r.stars ? "★" + r.stars : ""].filter(Boolean).join(" "))));
          const old = (S.scores[g] || {})[r.key];
          if (old && r.score < old.s) nm.append(h("div", { class: "w" }, "之前 ", scoreEl(g, old.s), "，会保留高的（下面勾「覆盖」才会改低）"));
          if (r.note) nm.append(h("div", { class: "w", text: r.note }));
          if (r.warn) nm.append(h("div", { class: "w", text: r.warn }));
        } else {
          nm.append(h("div", { class: "t", text: r.title_in || r.raw }), h("div", { class: "e", text: "第 " + r.line + " 行：" + (r.err || "没认出") }));
        }
        if ((r.choices || []).length) {           // 认不准：给个下拉自己选
          const s2 = h("select", null, h("option", { value: "", text: "选是哪首…" }),
            r.choices.map((c) => h("option", { value: c.k, text: c.t + (c.a ? " — " + c.a.slice(0, 24) : "") })));
          if (r.k) s2.value = r.k;
          s2.addEventListener("change", () => {
            const song = ix.byKey[s2.value];
            if (!song) return;
            const ch = chartFor(song, r.diff_in);
            r.k = song.k; r.t = song.t;
            if (ch) { r.key = ch.key; r.d = ch.d; r.lv = ch.l; r.use = true; r.err = ""; }
            else { r.key = ""; r.err = song.t + " 没有 " + r.diff_in; }
            li.className = "brow" + (r.key ? "" : " bad");
            draw(); refreshFoot();
          });
          nm.append(s2);
        }
        li.replaceChildren(cb, r.k ? jacket(g, r.k, 34, lazy) : h("div", { class: "jk s34" }), nm, h("span", { class: "stt " + cls, text: label }));
      };
      draw();
      list.append(li);
    });
    const good = rows.filter((r) => r.key).length;
    out.append(h("section", { class: "panel" },
      h("h2", null, "识别结果", h("small", { text: "认出 " + good + " / " + rows.length + " 行" + (good < rows.length ? " · 没认出的可以下拉选，或者改了再识别" : "") })),
      list,
      hiddenOk ? h("p", { class: "old", text: "还有 " + hiddenOk + " 行认出来了，没全列出来（都会一起传）。" }) : null,
      h("div", { class: "bfoot" }, h("label", { class: "check" }, over, "覆盖（传错了要改低时勾上；平时只保留更高的）"), footBtn)));
    footBtn.addEventListener("click", async () => {
      const pick = sel();
      if (!pick.length) return;
      if (over.checked && !confirm("勾了覆盖：比之前低的也会改成这里的分。确定？")) return;
      footBtn.disabled = true;
      const d = await api("/api/sb/batch_apply", { game: g, overwrite: over.checked,
        rows: pick.map((r) => ({ key: r.key, score: r.score, lamp: r.lamp, fb: r.fb, stars: r.stars, plat: r.plat, ex: r.ex })) });
      if (!d.ok) { toast(d.message || "没传上"); refreshFoot(); if (d._status === 401) { S.me.login = false; showGuest(); } return; }
      S.scores[g] = d.scores || S.scores[g]; S.summary[g] = d.summary; renderSum();
      const word = g === "sdvx" ? "VF" : "rating";
      const dl = d.delta ? "（" + word + " " + (d.delta > 0 ? "+" : "") + fk(d.delta) + "）" : "";
      out.replaceChildren(h("section", { class: "panel" },
        h("h2", null, "传好了 " + d.done + " 张" + dl),
        h("div", { class: "old", text: [d.unchanged ? d.unchanged + " 张和之前一样" : "", d.kept_higher ? d.kept_higher + " 张之前更高、保留了高的" : ""].filter(Boolean).join("，") }),
        (d.errors || []).length ? h("div", { class: "err", text: d.errors.join("；") }) : null,
        h("div", { class: "row tight mt" },
          h("button", { type: "button", class: "primary", text: "看我的成绩", onclick: () => setView("mine") }),
          h("button", { type: "button", class: "ghost", text: "再传一批", onclick: () => { $("bText").value = ""; out.replaceChildren(); $("bText").focus(); } }))));
      toast("传好了 " + d.done + " 张" + dl);
      S.batch = null;
    });
    refreshFoot();
  }

  // 链接 # 后面的参数：t 登录码、g 游戏、q 搜索词、k 歌、d 难度（/sdvx 传分 歌名 生成）
  function readHash() {
    const hp = new URLSearchParams(location.hash.slice(1));
    const o = {};
    ["t", "g", "q", "k", "d", "v"].forEach((x) => { if (hp.get(x)) o[x] = hp.get(x); });
    if (location.hash) history.replaceState(null, "", location.pathname);
    return o;
  }
  // 等确认码的状态存在浏览器里：人要切去 QQ 回确认码，手机上 / QQ 自带的网页窗口里这一切换，页面常常就被关掉或者刷新了。
  // 以前页面一没，等确认的那个编号也跟着没了，回来只能看到「没登录」。现在重新打开本站（同一个浏览器）会接着等、接着登录。
  function readPend() {
    try {
      const v = JSON.parse(store.get("sb_pend") || "null");
      if (v && v.p && v.c && v.e > Date.now() + 2000) return v;
    } catch (e) { /* 存坏了就当没有 */ }
    store.del("sb_pend");
    return null;
  }
  async function login(t) {
    let d = null;
    if (t) {
      d = await api("/api/sb/login", { t });
      if (d.pending) d = await waitConfirm(d);
    }
    if (!(d && d.ok)) {                                   // 没带登录码，或者这条链接已经点过一次（页面被关了又点开）：看看有没有等到一半的
      const saved = readPend();
      if (saved) d = await waitConfirm({ pid: saved.p, code: saved.c, ttl: Math.round((saved.e - Date.now()) / 1000), resumed: true });
    }
    if (!d) return false;
    if (d.ok) {
      const me = await api("/api/sb/me");
      if (me && me.login === false) {                     // 服务器说登录好了，可这个浏览器没把登录状态留住
        toast("登录成功了，但这个浏览器没存住登录状态（无痕模式 / 禁用了 cookie 会这样）。换系统浏览器打开，或私聊发「/传分」再点链接。");
        return false;
      }
      toast("登录好了，30 天内在这个浏览器直接打开这个网址就行");
    } else if (d.message) toast(d.message);
    return !!d.ok;
  }
  // 群里发的链接：显示 4 位码，等发命令的人自己在 QQ 回「/传分 确认 码」；别人点开的就一直卡在这
  function waitConfirm(d) {
    return new Promise((done) => {
      const left = h("div", { class: "pend-left" });
      const again = h("button", { type: "button", class: "pend-go", text: "我回过了，看看登上没", onclick: () => tick(true) });
      const cmd = "/传分 确认 " + d.code;
      const copyBtn = h("button", { type: "button", class: "pend-copy", "aria-label": "复制「" + cmd + "」" },
        h("b", { text: cmd }), h("span", { class: "pend-copy-tip", text: "点一下复制" }));
      let copyTimer = 0;
      copyBtn.addEventListener("click", async () => {
        const ok = await copyText(cmd);
        const tip = copyBtn.lastChild;
        copyBtn.classList.toggle("done", ok);
        tip.textContent = ok ? "已复制，去 QQ 粘贴发出去" : "没复制上，长按上面这行手动复制";
        clearTimeout(copyTimer);
        copyTimer = setTimeout(() => { copyBtn.classList.remove("done"); tip.textContent = "点一下复制"; }, 4000);
      });
      const box = h("div", { class: "pend-bg" }, h("div", { class: "pend" },
        h("img", { class: "pend-girl", src: "/img/yume-shh.webp", alt: "", width: 520, height: 386 }),
        h("div", { class: "pend-rule" }, h("i"), h("i")),
        h("div", { class: "pend-t", text: "还差一步：确认是你本人" }),
        h("div", { class: "pend-code", text: d.code }),
        h("div", { class: "pend-cmd" }, "在 QQ 里（群里或私聊 bot 都行）发：", copyBtn),
        h("div", { class: "pend-note", text: "要用发「/传分」的那个 QQ 发。这个链接是在群里发的，别人点开了也登不上你的号。别人报给你的码不要发。" }),
        h("div", { class: "pend-note keep", text: "发完回到这个页面。页面被关掉 / 刷新了也没事：用同一个浏览器重新打开本站，会接着等、接着登录。" }),
        left, again,
        h("button", { type: "button", class: "ghost", text: "不是我的链接，关掉", onclick: () => finish({ ok: false, message: "没登录" }) })));
      document.body.append(box);
      const end = Date.now() + (d.ttl || 300) * 1000;
      store.set("sb_pend", JSON.stringify({ p: d.pid, c: d.code, e: end }));
      let timer = null, gone = false, busy = false;
      // 人会切去 QQ 回确认码：这时页面在后台，定时器会被浏览器放慢，请求也可能直接失败。
      // 所以：请求失败不停（v2.3.9 及以前失败一次就再也不问了）；页面一回到前台马上再问一次。
      const wake = () => { if (!document.hidden) tick(true); };
      const EVENTS = ["visibilitychange", "focus", "pageshow", "online"];
      EVENTS.forEach((ev) => (ev === "visibilitychange" ? document : window).addEventListener(ev, wake));
      function finish(r) {
        if (gone) return;
        gone = true; clearTimeout(timer);
        store.del("sb_pend");
        EVENTS.forEach((ev) => (ev === "visibilitychange" ? document : window).removeEventListener(ev, wake));
        box.remove(); done(r);
      }
      async function tick(now) {
        if (gone) return;
        if (busy) return;                               // 上一次还没回来
        clearTimeout(timer);
        const sec = Math.max(0, Math.round((end - Date.now()) / 1000));
        if (sec <= 0) return finish({ ok: false, message: "确认码过期了。回 QQ 再发一次「/传分」" });
        left.textContent = (now ? "正在看… " : "等你确认… ") + "还剩 " + Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
        busy = true;
        let r;
        try { r = await api("/api/sb/pending", { p: d.pid }); } catch (e) { r = { offline: true, _status: 0 }; }
        busy = false;
        if (gone) return;
        if (r.ok) return finish(r);
        if (!r.wait && !r.offline && r._status !== 429 && r._status < 500) return finish(r);
        if (r.offline) left.textContent = "网络断了一下，接着等… 还剩 " + Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
        timer = setTimeout(tick, 2000);
      }
      tick();
    });
  }
  async function goTo(nav) {
    if (["find", "batch", "mine"].includes(nav.v)) setView(nav.v);
    if (nav.q || nav.k) { setView("find"); }
    if (nav.k) {
      const s = S.idx[S.game] && S.idx[S.game].byKey[nav.k];
      if (s) {
        $("q").value = s.t; $("qx").hidden = false;
        S.hits = [{ k: s.k }]; S.query = s.t; renderList();
        openSheet(s.k, nav.d || "");
        return;
      }
    }
    if (nav.q) { $("q").value = nav.q; onSearch(); }
    if (nav.d && !nav.k) { $("fDiff").value = SDVX_SPECIAL.includes(nav.d) ? "4TH" : nav.d; }
  }
  async function applyHash(first) {
    const nav = readHash();
    if (!first && !Object.keys(nav).length) return;
    if (nav.t || (first && readPend())) {
      const ok = await login(nav.t || "");
      if (ok || !first) { S.me = await api("/api/sb/me"); showGuest(); S.scores = {}; S.summary = {}; }
    }
    let g = ["sdvx", "geki"].includes(nav.g) ? nav.g : "";
    if (first && !g) g = store.get("sb_game") || "";
    if (!["sdvx", "geki"].includes(g)) g = first ? "sdvx" : S.game;
    if (first || g !== S.game || nav.t) { if (nav.q || nav.k) $("q").value = ""; await setGame(g); }
    await goTo(nav);
  }

  // ---------- 入口页 ----------
  // 页面一打开入口页就在（看板娘 + 两扇门），登录状态和曲库在后面照常加载；选一个游戏才进去。
  // 直达某首歌 / 搜索的链接、这个标签页已经进过一次：不放入口页。
  const calm = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  let gateOn = (() => {
    const hp = new URLSearchParams(location.hash.slice(1));
    let seen = false;
    try { seen = sessionStorage.getItem("sb_gate") === "1"; } catch (e) { /* 无痕模式 */ }
    return !(seen || hp.get("k") || hp.get("q"));
  })();
  if (!gateOn) $("gate").hidden = true;
  function gateClose() {
    if (!gateOn) return;
    gateOn = false;
    try { sessionStorage.setItem("sb_gate", "1"); } catch (e) { /* 无痕模式 */ }
    const gate = $("gate");
    window.scrollTo(0, 0);
    if (calm) { gate.hidden = true; return; }
    gate.classList.add("leave");
    document.body.classList.add("entering");
    setTimeout(() => { gate.hidden = true; }, 360);
    setTimeout(() => document.body.classList.remove("entering"), 900);
  }
  async function gateReady() {
    if (!gateOn) return;
    const login = S.me && S.me.login;
    if (login) {                                          // 两扇门上都写上现在的 VF / Rating
      try { await Promise.all(["sdvx", "geki"].filter((g) => S.summary[g] === undefined).map(loadScores)); } catch (e) { /* 门上不写就是了 */ }
    }
    $("gateWho").textContent = login ? (S.me.name || "QQ " + S.me.qq) + "\n已登录。" : "现在是只读模式\n能逛曲库。";
    $("gateNote").textContent = login ? "分数只升不降，传错了可以勾「覆盖」改。"
      : "想传分：QQ 里发「/传分 登录」，点它回你的链接就登录了。";
    const cats = (S.me && S.me.catalogs) || {};
    [["sdvx", "doorSdvx"], ["geki", "doorGeki"]].forEach(([g, id]) => {
      const sm = S.summary[g];
      $(id).textContent = sm && sm.count ? (g === "sdvx" ? "VF " : "Rating ") + sm.total_text + " · 已传 " + sm.count + " 张"
        : cats[g] ? "曲库 " + cats[g].songs + " 首" : "";
    });
    document.querySelectorAll("#gate .door").forEach((b) => {
      b.disabled = false;
      b.classList.toggle("cur", b.dataset.game === S.game);
      b.addEventListener("click", async () => {
        if (b.dataset.game !== S.game) await setGame(b.dataset.game);
        gateClose();
      });
    });
  }
  function markFresh() {                                  // 换游戏 / 刚进来：列表前几行依次浮上来（打字搜索时不放）
    const l = $("list");
    l.classList.remove("fresh"); void l.offsetWidth; l.classList.add("fresh");
  }

  async function init() {
    S.me = await api("/api/sb/me");
    showGuest();
    $("q").addEventListener("input", onSearch);
    $("qx").addEventListener("click", () => { $("q").value = ""; onSearch(); $("q").focus(); });
    ["fLevel", "fDiff", "fVer", "fGenre", "fState", "fSort"].forEach((id) => $(id).addEventListener("change", () => { S.shown = 50; renderList(); }));
    $("fToggle").addEventListener("click", () => toggleFilters());
    S.showConst = store.get("sb_geki_const") === "1";
    $("constTog").checked = S.showConst;
    $("constTog").addEventListener("change", () => {
      S.showConst = $("constTog").checked; store.set("sb_geki_const", S.showConst ? "1" : "0");
      renderList(); if (S.view === "mine") renderMine();
    });
    $("extraTog").addEventListener("change", async () => {
      const k = EXTRA_KEY[S.game], on = $("extraTog").checked;
      store.set("sb_show_" + k, on ? "1" : "0");
      if (S.me && S.me.login) {
        const d = await api("/api/sb/show", { k, on });
        if (d.ok) { S.me.show = d.show; toast((on ? "会显示" : "不显示") + (S.game === "sdvx" ? " EX SCORE" : "白金分") + "（网站和 b50 图都按这个）"); }
      } else if (S.me) { S.me.show = Object.assign({}, S.me.show || {}, { [k]: on }); }
      renderList(); if (S.view === "mine") renderMine();
    });
    $("fReset").addEventListener("click", () => { FILTER_IDS.forEach((id) => ($(id).value = "")); $("fSort").value = "new"; S.shown = 50; renderList(); });
    if (window.matchMedia("(min-width: 640px)").matches) toggleFilters(true);
    $("batchTipGo").addEventListener("click", () => { $("batchTip").hidden = true; setView("batch"); });
    $("batchTipX").addEventListener("click", () => { $("batchTip").hidden = true; store.set("sb_batch_tip_off", "1"); });
    $("bParse").addEventListener("click", batchParse);
    $("bSample").addEventListener("click", () => { $("bText").value = SAMPLE[S.game]; $("bText").focus(); });
    $("bClear").addEventListener("click", () => { $("bText").value = ""; $("bOut").replaceChildren(); S.batch = null; $("bText").focus(); });
    $("bCsv").addEventListener("change", async (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      if (!f) return;
      if (f.size > 2 * 1024 * 1024) { toast("文件太大了（最多 2 MB）"); return; }
      const buf = await f.arrayBuffer();
      let text;
      try { text = new TextDecoder("utf-8", { fatal: true }).decode(buf); }
      catch (err) { text = new TextDecoder("shift_jis").decode(buf); }          // 万一是 Shift_JIS
      $("bText").value = text;
      toast("读进来了：" + (text.split(/\r?\n/).length - 1) + " 行，正在识别");
      batchParse();
    });
    $("bText").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); batchParse(); } });
    $("bCopy").addEventListener("click", async () => toast(await copyText(AI_PROMPT[S.game]) ? "提示词复制好了，连同截图发给别的 AI" : "复制失败，手动长按复制吧"));
    window.addEventListener("resize", fixBarHeight);
    $("more").addEventListener("click", () => { S.shown += 50; renderList(); });
    document.querySelectorAll("#games button").forEach((b) => b.addEventListener("click", () => setGame(b.dataset.game)));
    document.querySelectorAll(".views button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
    $("sheetBg").addEventListener("click", closeSheet);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.sheet) closeSheet(); });
    // 页面开着时又点了新链接：浏览器只改 # 不重新加载，这里接住
    window.addEventListener("hashchange", () => applyHash(false));
    await applyHash(true);
    gateReady();
  }
  init();
})();
