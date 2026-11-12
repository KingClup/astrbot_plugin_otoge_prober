(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
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
  var params = new URLSearchParams(location.hash.slice(1));
  var token = params.get("t") || "";
  // 令牌只在 # 后面：存进本标签页的 sessionStorage，再从地址栏抹掉，防止截图 / 转发链接时带出去
  try {
    if (token) { sessionStorage.setItem("bind_t", token); if (params.get("g")) sessionStorage.setItem("bind_g", params.get("g")); }
    else { token = sessionStorage.getItem("bind_t") || ""; if (!params.get("g")) params.set("g", sessionStorage.getItem("bind_g") || ""); }
    history.replaceState(null, "", location.pathname);
  } catch (e) {}

  var SERVERS = {
    mai: [["intl", "国际服"], ["jp", "日服"], ["cn", "国服"], ["priv", "私服"]],
    chu: [["intl", "国际服"], ["jp", "日服"], ["cn", "国服"], ["priv", "私服"]],
    geki: [["jp", "官服"], ["priv", "私服"]],
    sdvx: [["jp", "官服"]]
  };
  // 私服：一个绑定舞萌 / 中二 / 音击共用；方式就是选哪个私服
  var PRIV_METHODS = [["munet", "MuNET", "填网站用户名；不是密码", ""], ["aqua", "AquaDX", "填网站用户名；不是密码", ""],
                      ["rin", "RinNET", "账号 + 密码登录一次，只存登录令牌", ""],
                      ["rin_token", "RinNET（令牌）", "GitHub / 微软等第三方登录、没有密码时用", ""]];
  var PRIV = [["munet", "MuNET"], ["rin", "RinNET"], ["aqua", "AquaDX"]];
  var FIELD = { munet: "user", aqua: "user", rin: "rinlogin", rin_token: "rintoken" };
  var SITE = { munet: "portal.mumur.net/u/<用户名>", aqua: "aquadx.net/u/<用户名>" };
  var METHODS = {
    "mai/intl": [["sega", "SEGA ID + 密码", "手机方便；clal 过期能自动续登", "推荐"], ["clal", "clal", "电脑上复制 Cookie 里的 clal"]],
    "mai/jp": [["sega", "SEGA ID + 密码", "日服只能用账号登录"]],
    "mai/cn": [["lx", "落雪个人密钥", "手动粘贴个人 API 密钥；能查全部成绩"], ["df", "水鱼查分器", "不用密钥，填用户名就行"]],
    "chu/intl": [["sega", "SEGA ID + 密码", "手机方便；clal 过期能自动续登", "推荐"], ["clal", "clal", "电脑上复制 Cookie 里的 clal"]],
    "chu/jp": [["sega", "SEGA ID + 密码", "日服用账号登录 CHUNITHM-NET"]],
    "chu/cn": [["lx", "落雪个人密钥", "手动粘贴个人 API 密钥；能查全部成绩"], ["df", "水鱼查分器", "不用密钥；只有 B30 / R10"]],
    "mai/priv": PRIV_METHODS,
    "chu/priv": PRIV_METHODS,
    // 音击只有 AquaDX 能查（MuNET 挡第三方、RinNET 还没做音击）；绑了照样是三个游戏共用
    "geki/priv": [["aqua", "AquaDX", "填网站用户名；不是密码。音击私服现在只有 AquaDX 能查", "唯一"]],
    // 官服（オンゲキ-NET / e-amusement）免费账号看不到成绩：没有绑定，进传分网站手动传
    "geki/jp": [["sega", "SEGA ID + 密码（自动查）", "账号要开 オンゲキ-NET Standard（330 円/月）才读得到成绩；还没实测过"],
                ["scores", "手动传分", "不开会员也行：在传分网站自己传（能批量）", "推荐"]],
    "sdvx/jp": [["scores", "手动传分", "e-amusement 不开会员看不到成绩；在传分网站自己传（能批量）", "唯一"]]
  };
  // 落雪授权 / 按 QQ：要 bot 主人配置过才出现（/api/session 里的 lx）
  function addLxMethods(lx) {
    ["mai", "chu"].forEach(function (g) {
      var list = METHODS[g + "/cn"].slice();
      if (lx && lx.qq) list.unshift(["lxqq", "落雪（按 QQ）", "什么都不用填，按你的 QQ 去落雪找；只有 B50 范围", lx.oauth ? "" : "推荐"]);
      if (lx && lx.oauth) list.unshift(["lxoauth", "落雪授权", "跳到落雪点一下「授权」；能查全部成绩，舞萌中二一次搞定", "推荐"]);
      if (!lx || (!lx.oauth && !lx.qq)) list[0] = list[0].slice(0, 3).concat(["推荐"]);
      METHODS[g + "/cn"] = list;
    });
  }
  var NET = { mai: "maimaidx-eng.com", chu: "chunithm-net-eng.com/mobile/" };
  var NAMES = { mai: "舞萌", chu: "中二", geki: "音击", sdvx: "SDVX" };
  var FULL = { mai: "舞萌 DX", chu: "中二节奏", geki: "音击", sdvx: "SDVX" };
  var SNAME = { intl: "国际服", jp: "日服", cn: "国服", priv: "私服" };

  var state = { game: "", server: "", method: "", consent: {}, expires: 0, busy: false, claim: "" };
  // 群链接的「这个浏览器」标记存 localStorage：去 QQ 回确认码时页面常被关掉 / 刷新，回来得还是同一个
  var claimKey = "bind_c_" + token.slice(0, 8);
  function loadClaim() {
    try { return localStorage.getItem(claimKey) || sessionStorage.getItem(claimKey) || ""; } catch (e) { return ""; }
  }
  function saveClaim(c) {
    try { localStorage.setItem(claimKey, c); } catch (e) {}
    try { sessionStorage.setItem(claimKey, c); } catch (e) {}
  }
  state.claim = loadClaim();

  function api(path, body) {
    var opt = { method: body ? "POST" : "GET", headers: { "X-Bind-Token": token }, cache: "no-store", credentials: "omit" };
    if (state.claim) opt.headers["X-Bind-Claim"] = state.claim;
    if (body) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { j._status = r.status; return j; });
    });
  }

  // ---------- 开场 ----------
  // 开场页一打开就在（看板娘 + 通行证），核对链接在后台同时进行，不会因为开场晚领链接。
  // 同一个标签页里看过一次就不再放（比如从落雪授权、传分网站跳回来）。
  var introKey = "bind_i_" + token.slice(0, 8), autoTimer = 0, entered = false;
  var calm = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  function introSeen() { try { return sessionStorage.getItem(introKey) === "1"; } catch (e) { return false; } }
  function showMain(animate) {
    var m = $("main"); m.hidden = false;
    if (animate && !calm) m.classList.add("enter");
  }
  function dropIntro() { entered = true; clearTimeout(autoTimer); $("intro").hidden = true; }
  function enter() {
    if (entered) return;
    entered = true; clearTimeout(autoTimer);
    try { sessionStorage.setItem(introKey, "1"); } catch (e) {}
    var intro = $("intro");
    if (calm) { intro.hidden = true; showMain(false); return; }
    intro.classList.add("leave");
    setTimeout(function () { intro.hidden = true; showMain(true); window.scrollTo(0, 0); }, 340);
  }
  function stopAuto() {
    if (entered || !autoTimer) return;
    clearTimeout(autoTimer); autoTimer = 0;
    $("enter").classList.remove("count");
    $("autoNote").textContent = "看好了就点上面的按钮";
  }
  function introReady() {
    var b = $("enter");
    b.disabled = false; b.textContent = "开始绑定"; b.classList.add("count");
    $("autoNote").textContent = "不点也行，3 秒后自己进去";
    autoTimer = setTimeout(enter, 3000);
  }

  function expired(claimed) {
    try { sessionStorage.removeItem("bind_t"); } catch (e) {}
    dropIntro(); showMain(false); $("remain").hidden = true;
    $("app").hidden = true; $("expired").hidden = false;
    $("who").textContent = "";
    if (claimed) {
      $("expiredTitle").textContent = "这个链接已经确认给别的设备了";
      $("expiredWhy").textContent = "群里发的链接要本人在 QQ 回确认码才能用，它已经确认给另一个浏览器了（或者被点开太多次）。";
    }
  }

  function radio(container, items, current, onPick, cls) {
    container.textContent = "";
    items.forEach(function (it) {
      var b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", it[0] === current ? "true" : "false");
      if (cls) b.className = cls;
      if (cls === "method") {
        var t = document.createElement("b"); t.textContent = it[1];
        if (it[3]) { var tag = document.createElement("span"); tag.className = "tag"; tag.textContent = it[3]; t.appendChild(tag); }
        var s = document.createElement("small"); s.textContent = it[2];
        b.appendChild(t); b.appendChild(s);
      } else { b.textContent = it[1]; }
      b.addEventListener("click", function () { onPick(it[0]); });
      container.appendChild(b);
    });
  }

  function renderBound(bound) {
    var box = $("bound"); box.textContent = "";
    var rest = 0;
    function chip(cls, label, on) {
      if (!on) { rest += 1; return; }
      var c = document.createElement("span");
      c.className = "chip " + cls; c.textContent = label;
      box.appendChild(c);
    }
    ["mai", "chu"].forEach(function (g) {
      SERVERS[g].forEach(function (sv) {
        if (sv[0] === "priv") return;
        var v = (bound[g] || {})[sv[0]];
        var label = NAMES[g] + " " + sv[1];
        if (v === "lx") label += "（落雪密钥）"; else if (v === "lxoauth") label += "（落雪授权）";
        else if (v === "lxqq") label += "（落雪 · 按 QQ）"; else if (v === "df") label += "（水鱼）";
        chip(g, label, v);
      });
    });
    chip("geki", "音击 官服（SEGA ID 自动查）", (bound.geki || {}).jp);
    PRIV.forEach(function (sv) {      // 私服一个绑定几个游戏都能用：只列一次
      var on = (bound.mai || {})[sv[0]] || (bound.chu || {})[sv[0]];
      chip("priv", "私服 " + sv[1] + (sv[0] === "aqua" ? "（舞萌 / 中二 / 音击共用）" : "（舞萌中二共用）"), on);
    });
    var r = document.createElement("span");
    r.className = "chip rest";
    r.textContent = box.childNodes.length ? "其他 " + rest + " 项还没绑" : "还没绑过，从下面选游戏开始";
    if (rest) box.appendChild(r);
  }

  function pickGame(g) {
    state.game = g;
    document.querySelectorAll(".game").forEach(function (b) { b.setAttribute("aria-checked", b.dataset.game === g ? "true" : "false"); });
    var list = SERVERS[g];
    if (!list.some(function (s) { return s[0] === state.server; })) state.server = list.length === 1 ? list[0][0] : "";   // 只有一个区服（SDVX）直接选上
    $("serverCard").hidden = false;
    radio($("servers"), list, state.server, pickServer);
    if (state.server) pickServer(state.server); else { $("methodCard").hidden = true; $("form").hidden = true; }
  }

  function pickServer(s) {
    state.server = s;
    radio($("servers"), SERVERS[state.game], s, pickServer);
    var ms = METHODS[state.game + "/" + s];
    if (!ms.some(function (m) { return m[0] === state.method; })) state.method = ms[0][0];
    // 只有一种方式时也显示第 3 步（就那一个选项，已经选好），步骤编号不会从 2 跳到 4
    $("methodCard").hidden = false;
    pickMethod(state.method);
  }

  function pickMethod(m) {
    state.method = m;
    var ms = METHODS[state.game + "/" + state.server];
    radio($("methods"), ms, m, pickMethod, "method");
    var field = state.server === "priv" ? FIELD[m] : m;
    document.querySelectorAll(".field").forEach(function (f) { f.classList.toggle("show", f.dataset.for === field); });
    var label = ms.filter(function (x) { return x[0] === m; })[0][1];
    $("formTitle").textContent = state.server === "priv" ? "私服 · " + label + (m === "aqua" ? "（舞萌 / 中二 / 音击共用）" : "（舞萌中二共用）")
                               : m === "scores" ? NAMES[state.game] + "官服 · 手动传分"
                                                : NAMES[state.game] + (state.game === "geki" || state.game === "sdvx" ? "官服" : SNAME[state.server]) + " · " + label;
    if (SITE[m]) $("privUserTip").textContent = "用户名是 " + SITE[m] + " 里那段，也可以直接粘贴个人主页链接。只是公开的用户名，不是密码。";
    $("netUrl").textContent = NET[state.game];
    $("clalAlt").textContent = "手机上不方便的话，上面改选「SEGA ID + 密码」。";
    $("segaTip").textContent = state.server === "jp" ? "日服每次都用 SEGA ID + 密码登录，绑一次就行。"
                                                     : "clal 过期时会用账号密码自动重新登录，不用再来绑。";
    var secret = ["df", "munet", "aqua", "lxqq", "scores"].indexOf(m) < 0;
    var text = m === "lx" ? state.consent.lx : m === "lxoauth" ? state.consent.lxoauth : state.consent.mai;
    $("go").textContent = goText(m);
    if (state.game === "chu" && m === "clal") {
      text = "1. 我会用你的 clal 登录 CHUNITHM-NET，只读取资料和成绩，不会改任何设置。\n" +
             "2. clal 会加密保存在 bot 主人的电脑上，不会发进群聊，不会交给 AI，日志里也会打码；但 bot 主人在技术上能接触到这台电脑。\n" +
             "3. 这是非官方工具，可能随官网改版失效。随时可以发 /chu 解绑 删除。";
    }
    if (state.game === "chu" && m === "lx") text = (text || "").replace(/\/mai 解绑 国服/g, "/chu 解绑 国服");
    if (state.game === "chu" && m === "sega") {
      var where = state.server === "jp" ? "日服 CHUNITHM-NET" : "国际服 CHUNITHM-NET（clal 过期时也用它自动重新登录）";
      text = "1. 我会用你的 SEGA ID 和密码登录" + where + "，只读取资料和成绩，不会改任何设置，也不会进行购买或好友操作。\n" +
             "2. 账号密码会加密保存在 bot 主人的电脑上，不会发进群聊，不会交给 AI，日志里也会打码；但 bot 主人在技术上能接触到这台电脑。\n" +
             "3. 这是非官方工具，可能随官网改版失效，账号因此出现的问题由你自己承担。随时可以发 /chu 解绑" + (state.server === "jp" ? " 日服" : "") + " 删除。";
    }
    if (state.game === "geki" && m === "sega") {
      text = "1. 我会用你的 SEGA ID 和密码登录 オンゲキ-NET，只读取逐曲成绩，不会改任何设置，也不会进行购买或好友操作。\n" +
             "2. 账号密码会加密保存在 bot 主人的电脑上，不会发进群聊，不会交给 AI，日志里也会打码；但 bot 主人在技术上能接触到这台电脑。\n" +
             "3. 要账号开着 Standard 会员才读得到成绩；没开也能绑，开了以后发 /geki 同步。读到的成绩会放进传分网站，和手动传的合在一起（只升不降）。\n" +
             "4. 这是非官方工具，还没有用真账号测过，官网改版可能失效。随时可以发 /geki 解绑 官服 删除。";
    }
    if (m === "rin" || m === "rin_token") {
      text = "1. " + (m === "rin" ? "我会用你的账号密码登录 RinNET 一次，拿到登录令牌后立刻丢掉密码，不保存。"
                                   : "我会用你的 refreshToken 登录 RinNET。") +
             "之后只读取舞萌 / 中二的资料和成绩，不会改任何设置。\n" +
             "2. 登录令牌会加密保存在 bot 主人的电脑上，不会发进群聊，不会交给 AI，日志里也会打码；但 bot 主人在技术上能接触到这台电脑。\n" +
             "3. 这是非官方工具，可能随 RinNET 改版失效。随时可以发 /mai 解绑 rin 删除；在 RinNET 网站上退出登录或改密码也会让令牌失效。";
    }
    $("consentText").textContent = text || "";
    $("consent").classList.toggle("show", secret);
    $("form").hidden = false;
    hideResult();
  }

  function goText(m) { return m === "lxoauth" ? "去落雪授权" : m === "scores" ? "进传分网站" : "绑定"; }
  function hideResult() { var r = $("result"); r.hidden = true; r.textContent = ""; $("resultGirl").hidden = true; }
  function showResult(ok, msg) {
    var r = $("result"); r.hidden = true; $("resultGirl").hidden = true;   // 先藏再显示：每次结果都重新演一下
    r.className = "result " + (ok ? "ok" : "bad"); r.textContent = msg;
    void r.offsetWidth;
    $("resultGirl").hidden = !ok; r.hidden = false;
  }

  function submit(ev) {
    ev.preventDefault();
    if (state.busy) return;
    var m = state.method, body = { game: state.game, server: state.server, method: m, agree: $("agree").checked };
    if (m === "clal") body.value = $("clal").value.replace(/^\s*clal\s*=\s*/i, "").trim();
    if (m === "lx") body.value = $("lxKey").value.trim();
    if (m === "df") body.value = $("dfName").value.trim();
    if (m === "sega") { body.sega_id = $("segaId").value.trim(); body.password = $("password").value; }
    if (m === "munet" || m === "aqua") body.value = $("privUser").value.trim();
    if (m === "rin") { body.account = $("rinAccount").value.trim(); body.password = $("rinPassword").value; body.code = $("rinCode").value.trim(); }
    if (m === "rin_token") body.value = $("rinToken").value.trim().replace(/^["']|["']$/g, "");
    if (m === "clal" && !/^[A-Za-z0-9]{64}$/.test(body.value)) return showResult(false, "clal 应该是 64 位字母和数字");
    if (m === "lx" && !body.value) return showResult(false, "先粘贴落雪密钥");
    if (m === "sega" && (!body.sega_id || !body.password)) return showResult(false, "SEGA ID 和密码都要填");
    if ((m === "munet" || m === "aqua") && !body.value) return showResult(false, "先填网站用户名");
    if (m === "rin" && (!body.account || !body.password)) return showResult(false, "账号和密码都要填");
    if (m === "rin" && body.code && !/^\d{6}$/.test(body.code)) return showResult(false, "两步验证码是 6 位数字");
    if (m === "rin_token" && !body.value) return showResult(false, "先粘贴 refreshToken");
    if (["df", "munet", "aqua", "lxqq", "scores"].indexOf(m) < 0 && !body.agree) return showResult(false, "要先勾选「我看完了，同意」");
    if (m === "scores") {
      state.busy = true; $("go").disabled = true; $("go").textContent = "正在打开";
      api("/api/sb/from_bind", { game: state.game }).then(function (j) {
        if (j.ok && j.url) { window.location.href = j.url; return; }
        showResult(false, j.message || "出错了，稍后再试");
        if (j._status === 401 || j._status === 409) setTimeout(function () { expired(j._status === 409); }, 2500);
      }).catch(function () { showResult(false, "网络不通，检查一下网络再点一次"); })
        .then(function () { state.busy = false; $("go").disabled = false; $("go").textContent = goText("scores"); });
      return;
    }
    if (m === "lxoauth") {
      state.busy = true; $("go").disabled = true; $("go").textContent = "正在跳转";
      api("/api/lx/start", { agree: true }).then(function (j) {
        if (j.ok && j.url) { window.location.href = j.url; return; }
        showResult(false, j.message || "出错了，稍后再试");
        state.busy = false; $("go").disabled = false; $("go").textContent = "去落雪授权";
      }).catch(function () {
        showResult(false, "网络不通，检查一下网络再点一次");
        state.busy = false; $("go").disabled = false; $("go").textContent = "去落雪授权";
      });
      return;
    }
    state.busy = true; $("go").disabled = true; $("go").classList.add("busy"); $("go").textContent = "正在验证";
    hideResult();
    api("/api/bind", body).then(function (j) {
      if (j._status === 401 || j._status === 409) {
        showResult(false, j.message || "链接已过期");
        setTimeout(function () { expired(j._status === 409); }, 2500); return;
      }
      showResult(!!j.ok, j.message || "出错了，稍后再试");
      if (j.bound) renderBound(j.bound);
      if (j.ok) { ["clal", "lxKey", "password", "rinPassword", "rinCode", "rinToken"].forEach(function (id) { $(id).value = ""; }); }
    }).catch(function () {
      showResult(false, "网络不通，检查一下网络再点一次");
    }).then(function () {
      state.busy = false; $("go").disabled = false; $("go").classList.remove("busy"); $("go").textContent = goText(state.method);
    });
  }

  function tick() {
    var left = Math.max(0, Math.round((state.expires - Date.now()) / 1000));
    var text = Math.floor(left / 60) + ":" + ("0" + (left % 60)).slice(-2);
    document.querySelectorAll(".js-left").forEach(function (el) { el.textContent = text; });
    if (left <= 0) { expired(); return; }
    setTimeout(tick, 1000);
  }

  document.querySelectorAll(".game").forEach(function (b) { b.addEventListener("click", function () { pickGame(b.dataset.game); }); });
  $("form").addEventListener("submit", submit);
  [["pwToggle", "password"], ["rinPwToggle", "rinPassword"]].forEach(function (pair) {
    $(pair[0]).addEventListener("click", function () {
      var p = $(pair[1]), show = p.type === "password";
      p.type = show ? "text" : "password"; this.textContent = show ? "隐藏" : "显示";
    });
  });

  $("enter").addEventListener("click", enter);
  // 手指碰了开场页别的地方（想多看一眼）：不自动进去了，等点按钮
  $("intro").addEventListener("pointerdown", function (ev) { if (!ev.target.closest || !ev.target.closest("#enter")) stopAuto(); });

  // ---------- 群里发的链接：先等本人在 QQ 回确认码 ----------
  var waitTimer = 0, waiting = false;
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return oldCopy(text); });
    }
    return Promise.resolve(oldCopy(text));
  }
  function oldCopy(text) {
    var ta = document.createElement("textarea");
    ta.className = "sr-copy"; ta.value = text; ta.setAttribute("readonly", "");
    document.body.appendChild(ta); ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }
  function showConfirm(j) {
    waiting = true;
    if (j.claim) { state.claim = j.claim; saveClaim(j.claim); }
    dropIntro(); showMain(false);
    $("app").hidden = true; $("expired").hidden = true; $("remain").hidden = true;
    $("confirm").hidden = false;
    $("confirmCode").textContent = j.code || "----";
    $("who").textContent = "";
    clearTimeout(waitTimer);
    waitTimer = setTimeout(checkConfirm, 2500);
  }
  function checkConfirm() {
    if (!waiting) return;
    clearTimeout(waitTimer);
    api("/api/session").then(function (j) {
      if (!waiting) return;
      if (j._status === 200 && j.pending) { showConfirm(j); return; }
      if (j._status === 200) { waiting = false; $("confirm").hidden = true; ready(j); return; }
      if (j._status === 401 || j._status === 409) { waiting = false; $("confirm").hidden = true; expired(j._status === 409); return; }
      waitTimer = setTimeout(checkConfirm, 4000);          // 429 / 5xx：慢一点接着问
    }).catch(function () { if (waiting) waitTimer = setTimeout(checkConfirm, 4000); });   // 断网 / 页面在后台：接着问
  }
  $("confirmCopy").addEventListener("click", function () {
    var btn = this, text = "/网页绑定 确认 " + $("confirmCode").textContent;
    copyText(text).then(function (ok) {
      $("confirmTip").textContent = ok ? "已复制，去 QQ 粘贴发出去" : "复制不上，长按上面那句手动复制";
      btn.classList.toggle("done", !!ok);
    });
  });
  $("confirmCheck").addEventListener("click", function () {
    $("confirmWait").textContent = "正在看…";
    checkConfirm();
    setTimeout(function () { if (waiting) $("confirmWait").textContent = "还没收到。确认码发给 bot 了吗？"; }, 1500);
  });
  ["visibilitychange", "focus", "pageshow", "online"].forEach(function (ev) {
    (ev === "visibilitychange" ? document : window).addEventListener(ev, function () {
      if (waiting && document.visibilityState !== "hidden") checkConfirm();
    });
  });

  function ready(j) {
    if (j._status !== 200) { expired(j._status === 409); if (j._status === 429) $("who").textContent = "请求太频繁，稍等一分钟再开"; return; }
    state.consent = j.consent || {};
    addLxMethods(j.lx);
    state.expires = Date.now() + (j.expires_in || 0) * 1000;
    var who = $("who"); who.textContent = "";
    var b = document.createElement("b"); b.textContent = j.qq;
    who.appendChild(document.createTextNode("绑到 QQ ")); who.appendChild(b);
    $("remain").hidden = false;
    renderBound(j.bound || {});
    $("app").hidden = false;
    var g = params.get("g");
    if (g === "mai" || g === "chu" || g === "geki" || g === "sdvx") pickGame(g);
    $("passQQ").textContent = j.qq;
    if (FULL[g]) $("passGame").textContent = FULL[g];
    tick();
    if (!entered) introReady();
  }

  if (!token) { expired(); return; }
  if (introSeen()) { dropIntro(); showMain(false); }
  api("/api/session").then(function (j) {
    if (j._status === 200 && j.pending) { showConfirm(j); return; }
    ready(j);
  }).catch(function () {
    dropIntro(); showMain(false);
    $("who").textContent = "连不上服务器，稍后刷新试试";
  });
})();
