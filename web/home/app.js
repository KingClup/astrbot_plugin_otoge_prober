/* 主页（v2.6.0）。没有框架、没有 innerHTML、没有行内样式（位置之类的数只通过 style.setProperty 写变量）。
   这个脚本在 <head> 里同步执行：先决定这次要不要放开场，给 <html> 挂好 class，页面第一帧就是对的。 */
(function () {
  "use strict";
  // 老的绑定链接是「/#t=令牌」，绑定页挪到 /bind 以后，带令牌打开根路径的原样转过去（# 后面的东西不会发给服务器）
  if (/(^#|&)t=/.test(location.hash)) { location.replace("/bind" + location.hash); return; }

  var root = document.documentElement;
  var PREVIEW = root.hasAttribute("data-preview");      // 预览页：不真的跳转，开场每次都放
  var GAMES = ["var(--mai)", "var(--chu)", "var(--geki)", "var(--sdvx)"];

  // 系统开了「减少动态效果」：什么都不动，就是一张静态页
  var fx = true;
  try { fx = !window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}
  var hover = false;
  try { hover = window.matchMedia("(hover: hover) and (pointer: fine)").matches; } catch (e) {}

  // 开场有两套分镜，每次随机放一套（各一半）：a = 跳出来，b = 飘起来。同一个标签页只放一次。
  // 帧的写法："a:名字" = 整个人离地 / 侧身的整框图（yume-a-*，加高画框，离地多高已经烤在图里），"p:名字" = 站着的动作差分（yume-p-*），"p:" = 定稿站姿。
  function frameUrl(f) { return window.Mascot.frameUrl(f); }
  // 三套开场。first：一开始那一帧；ms：演多久开始收场；play：开场里按时间换的帧（走路那套要）；
  // out：收场时她飞去主页站位的路上按时间换的帧；land：飞多久落定；after：落定那一刻、+170ms、+340ms 主页上的她依次是哪个动作差分（null = 站姿）。
  var OPS = {
    a: { first: "a:jump", ms: 2750, land: 1150, play: [],
         out: [[150, "a:tuck2"], [330, "a:unfold"], [520, "a:fall"], [720, "a:touch"], [900, "p:land"]], after: ["land", "settle", "wave"] },
    b: { first: "a:float", ms: 3250, land: 1350, play: [],
         out: [[380, "a:tilt"], [760, "a:upright"], [1120, "p:land"]], after: ["land", "settle", "wave"] },
    c: { first: "a:walk1", ms: 3700, land: 950,
         play: [[470, "a:pass"], [640, "a:walk2"], [810, "a:pass"], [980, "a:walk1"], [1150, "a:pass"], [1320, "a:walk2"], [1490, "a:pass"], [1660, "a:turn"], [1860, "p:"], [2180, "p:reach"], [2360, "p:curtsy"]],
         out: [[260, "p:reach"], [480, "p:"]], after: [null, null, "wave"] }
  };
  var KINDS = ["a", "b", "c"];
  var opKind = KINDS[Math.floor(Math.random() * KINDS.length)];
  try { var forced = /[?&]op=([abc])/.exec(location.search); if (forced) opKind = forced[1]; } catch (e) {}
  // 两张叠着的 <img> 轮流用：新的一帧先在看不见的那张里取好，取到了再换上来，不会闪一下空白
  var flipper = window.Mascot.flipper;
  var opFlip = null;
  var playOp = false, opEnded = true, opSkipped = false, afterOp = [], opTimer = 0, opTimers = [];
  if (fx) {
    root.classList.add("fx");
    var seen = null;
    try { seen = sessionStorage.getItem("yume-op"); } catch (e) {}
    if (!seen || PREVIEW) {
      playOp = true; opEnded = false;
      root.classList.add("op-play", "op-hold", "op-" + opKind);
      try { sessionStorage.setItem("yume-op", "1"); } catch (e) {}
    }
  }
  function startOp() {
    root.classList.remove("op-hold");
    clearTimeout(opTimer);
    opTimers.splice(0).forEach(clearTimeout);
    OPS[opKind].play.forEach(function (st) { opTimers.push(setTimeout(function () { if (opFlip) opFlip.show(st[1]); }, st[0])); });
    opTimer = setTimeout(function () { endOp(false); }, OPS[opKind].ms);
  }
  // 收场：不是「盖住再偷换」，而是开场这一层自己撤走（a：一条条轨道上下抽走；b：夜色收成一个圆缩进她的光环；c：整面往右卷走），
  // 同时她本人从开场的位置直接飞到主页的站位上，路上按 out 里的时间一帧一帧换姿势，落定以后换成主页上会动的那个她。主页自己的进场也从这一刻才开始。
  function endOp(skipped) {
    if (opEnded) return;
    opEnded = true;
    clearTimeout(opTimer);
    opTimers.splice(0).forEach(clearTimeout);
    root.classList.remove("op-hold");
    var oc = document.getElementById("op-cast"), cast = document.getElementById("cast"), op = document.getElementById("op");
    var gone = function () { root.classList.add("op-gone"); };
    opSkipped = !!(skipped || !oc || !cast || !op || document.body.classList.contains("no-yume"));
    if (opSkipped) {
      root.classList.add("op-bye");                     // 点了跳过：整层淡掉
      opTimers.push(setTimeout(gone, 320));
    } else {
      // 开场那一层的画框和主页站姿的画框是同一个，所以目标就是主页那个框本身
      var v = OPS[opKind], a = oc.getBoundingClientRect(), b = cast.getBoundingClientRect(), cx = b.left + b.width / 2;
      oc.style.setProperty("--dx", (cx - (a.left + a.width / 2)).toFixed(1) + "px");
      oc.style.setProperty("--dy", (b.top + b.height / 2 - (a.top + a.height / 2)).toFixed(1) + "px");
      oc.style.setProperty("--ds", (b.height / a.height).toFixed(4));
      op.style.setProperty("--ix", cx.toFixed(1) + "px");
      op.style.setProperty("--iy", (b.top + b.height * .12).toFixed(1) + "px");
      root.classList.add("op-out");
      v.out.forEach(function (st) { opTimers.push(setTimeout(function () { if (opFlip) opFlip.show(st[1]); }, st[0])); });
      opTimers.push(setTimeout(function () { root.classList.add("op-land"); }, v.land));
      opTimers.push(setTimeout(gone, v.land + 240));
    }
    afterOp.splice(0).forEach(function (fn) { fn(); });
  }
  function whenOpEnds(fn) { if (opEnded) fn(); else afterOp.push(fn); }

  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }
  function each(sel, fn) { Array.prototype.forEach.call(document.querySelectorAll(sel), fn); }
  function rnd(a, b) { return a + Math.random() * (b - a); }

  // 看板娘的骨架、图片地址、动作帧的换图都在 /yume.js 里（三个网站共用）
  var Y = window.Mascot, src = Y.src, makeRig = Y.makeRig;
  function poseSrc(name) { return src("yume-p-" + name); }
  function actSrc(name) { return src("yume-a-" + name); }

  document.addEventListener("DOMContentLoaded", function () {
    var body = document.body;
    var win = document.getElementById("window"), girl = document.getElementById("girl");
    var op = document.getElementById("op"), wipe = document.getElementById("wipe");

    // ---------- 看板娘图取不到（公开版包里没有）就换成光环，不留破图 ----------
    function noGirl() { if (win) win.classList.add("no-girl"); body.classList.add("no-yume"); }
    if (win && girl) {
      girl.addEventListener("error", noGirl);
      if (girl.complete && girl.naturalWidth === 0) noGirl();
    }

    // ---------- 开场：这次放哪一套就取哪张图，图到了再开演，点一下 / 按键跳过 ----------
    var opGirl = document.getElementById("op-girl"), opG2 = document.getElementById("op-g2");
    if (opGirl && opG2) opFlip = flipper(opGirl, opG2);
    function loadOp() {
      if (!opFlip) { startOp(); return; }
      var v = OPS[opKind], done = false, go = function () { if (!done) { done = true; startOp(); } };
      opFlip.first(v.first, go, function () { noGirl(); go(); });
      v.play.concat(v.out).forEach(function (st) { new Image().src = frameUrl(st[1]); });      // 后面要换的帧先取回来
      opTimer = setTimeout(go, 1500);
    }
    if (playOp) loadOp();
    if (PREVIEW) window.__opEnd = function () { endOp(false); };      // 预览里给检查脚本用：立刻正常收场
    if (fx) {
      if (op) op.addEventListener("click", function () { endOp(true); });
      document.addEventListener("keydown", function (e) {
        if (!opEnded && (e.key === "Escape" || e.key === "Enter" || e.key === " ")) endOp(true);
      });
    }

    // ---------- 通行证右上角写这次部署自己的地址 ----------
    each(".pass-host", function (e) { e.textContent = location.host + e.getAttribute("data-path"); });

    // ---------- 点指令 = 复制，顺手给一个判定 ----------
    var toast = document.getElementById("toast"), timer = 0, combo = 0, comboTimer = 0;
    function say(text) {
      toast.textContent = text;
      clearTimeout(timer);
      timer = setTimeout(function () { toast.textContent = ""; }, 2600);
    }
    function judge(btn, ok) {
      if (!fx) return;
      var r = btn.getBoundingClientRect(), j = el("div", "judge");
      j.style.setProperty("--x", (r.left + r.width / 2) + "px");
      j.style.setProperty("--y", r.top + "px");
      j.style.setProperty("--c", ok ? GAMES[combo % 4] : "var(--mute)");
      j.appendChild(document.createTextNode(ok ? "PERFECT" : "MISS"));
      if (ok && combo > 1) { var s = el("small"); s.textContent = combo + " COMBO"; j.appendChild(s); }
      body.appendChild(j);
      setTimeout(function () { j.remove(); }, 950);
    }
    each(".cmd", function (btn) {
      btn.addEventListener("click", function () {
        var cmd = btn.getAttribute("data-cmd");
        var fail = function () { combo = 0; judge(btn, false); say("复制不上，手动打 " + cmd + " 吧"); };
        var ok = function () {
          combo += 1;
          clearTimeout(comboTimer);
          comboTimer = setTimeout(function () { combo = 0; }, 6000);
          judge(btn, true);
          say("已复制 " + cmd + "，去 QQ 粘贴发出去");
        };
        try { navigator.clipboard.writeText(cmd).then(ok, fail); } catch (e) { fail(); }
      });
    });

    if (!fx) return;      // 下面全是动效

    // ---------- 大标题拆成一个字一个字，好让它们挨个升上来 ----------
    var hello = document.getElementById("hello");
    if (hello) {
      var lines = [""];
      Array.prototype.forEach.call(hello.childNodes, function (nd) {
        if (nd.nodeType === 3) lines[lines.length - 1] += nd.textContent.trim();
        else if (nd.nodeName === "BR") lines.push("");
      });
      hello.setAttribute("aria-label", lines.join(""));
      while (hello.firstChild) hello.removeChild(hello.firstChild);
      var idx = 0;
      lines.forEach(function (text) {
        var ln = el("span", "ln");
        ln.setAttribute("aria-hidden", "true");
        Array.from(text).forEach(function (c) {
          var ch = el("span", "ch");
          ch.textContent = c;
          ch.style.setProperty("--i", idx++);
          ln.appendChild(ch);
        });
        hello.appendChild(ln);
      });
    }

    // ---------- 条幅：把那一组字复制到够铺满屏幕，再按一组的宽度循环 ----------
    var run = document.querySelector(".band-run");
    function fillBand() {
      var set = run && run.querySelector(".band-set");
      if (!set) return;
      var w = set.getBoundingClientRect().width;
      if (!w) return;
      while (run.children.length * w < window.innerWidth * 2.2 && run.children.length < 12) run.appendChild(set.cloneNode(true));
      run.style.setProperty("--w", (-w) + "px");
      run.style.setProperty("--dur", Math.round(w / 24) + "s");
    }
    fillBand();
    window.addEventListener("resize", fillBand);

    // ---------- 背景里慢慢往下落的：四个游戏各自的音符剪影 ----------
    var NOTES = ["mai-star", "chu-air", "geki-bell", "sdvx-fx", "mai-hold", "chu-tap", "geki-side", "sdvx-laser", "mai-touch", "sdvx-bt"];      // 只留一眼认得出的
    var sky = document.getElementById("sky"), SVG = "http://www.w3.org/2000/svg";
    if (sky && document.getElementById("n-mai-star")) {
      var count = window.innerWidth < 720 ? 10 : 18;
      for (var i = 0; i < count; i++) {
        var name = NOTES[i % NOTES.length], n = document.createElementNS(SVG, "svg"), use = document.createElementNS(SVG, "use");
        var dur = rnd(18, 36), r0 = rnd(-24, 24), spin = name === "mai-star" ? rnd(120, 240) : rnd(-36, 36);
        use.setAttribute("href", "#n-" + name);
        n.setAttribute("class", "g-" + name.split("-")[0]);
        n.setAttribute("viewBox", "0 0 48 48");
        n.appendChild(use);
        n.style.setProperty("--x", rnd(1, 96).toFixed(1) + "%");
        n.style.setProperty("--s", Math.round(rnd(16, 34)) + "px");
        n.style.setProperty("--o", rnd(.2, .46).toFixed(2));
        n.style.setProperty("--d", dur.toFixed(1) + "s");
        n.style.setProperty("--dl", (-rnd(0, dur)).toFixed(1) + "s");
        n.style.setProperty("--r0", r0.toFixed(0) + "deg");
        n.style.setProperty("--r1", (r0 + spin).toFixed(0) + "deg");
        sky.appendChild(n);
      }
    }
    // ---------- 顶上的进度线 ----------
    var prog = document.querySelector(".prog"), ticking = false;
    function onScroll() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        ticking = false;
        var max = root.scrollHeight - window.innerHeight;
        if (prog) prog.style.setProperty("--sp", max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)).toFixed(4) : "0");
      });
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    // ---------- 滚到了才演：等开场结束再开始看 ----------
    function reveal(e) {
      e.classList.add("in");
      setTimeout(function () { e.classList.add("done"); }, 2600);
    }
    whenOpEnds(function () {
      if (!("IntersectionObserver" in window)) { each(".fx-in", reveal); return; }
      var io = new IntersectionObserver(function (items) {
        items.forEach(function (it) { if (it.isIntersecting) { io.unobserve(it.target); reveal(it.target); } });
      }, { threshold: .16, rootMargin: "0px 0px -6% 0px" });
      each(".fx-in", function (e) { io.observe(e); });
    });

    // ---------- 看板娘：跟着鼠标轻轻错位；点她（或者点台词框）换一个动作、说一句话 ----------
    // p = 动作差分的名字（只换上半身和表情），a = 整个人离地的动作（跳、飘），t = 台词
    var HELLO = { p: "wave", t: "欢迎回来。要查分，还是绑账号？" };
    var BEATS = [
      { p: "shh", t: "密码只填网页里，别发到群里哦。" },
      { p: "point", t: "怎么走都写在那边，看一眼再进。" },
      { p: "cheer", t: "今天也要 AP 一首再走。" },
      { p: "pout", t: "B50 掉分了？不是我干的。" },
      { a: "float", t: "状态好的时候，感觉人都能飘起来。" },
      { p: "card", t: "绑定链接十分钟内有效，过期了再要一条。" },
      { p: "think", t: "嗯……你上次查分是什么时候来着？" },
      { p: "clap", t: "出新纪录了？好耶，恭喜恭喜。" },
      { a: "jump", t: "嘿咻——看，跳得高吧。" },
      { p: "heart", t: "谢谢你来看我。" },
      { p: "ok", t: "查分的话，回群里喊我就行。" },
      { p: "peace", t: "下次出勤，也带上我。" }
    ];
    var FUSS = [{ p: "surprise", t: "诶、别戳那么快——" }, { p: "shy", t: "别、别一直戳啦……" }];      // 连着猛点
    var INVITE = [{ p: "wave", t: "戳戳我，或者点这个框，可以跟我说话。" }, { p: "ok", t: "点一下试试？我会换动作的。" }];   // 还没人点过
    var IDLE = [                                                                                        // 点过以后，隔一阵自己冒一句
      { p: "think", t: "……在想今天推哪首。" },
      { p: "peace", t: "我还在这儿哦。" },
      { p: "card", t: "要绑账号的话，先回 QQ 发 /网页绑定。" },
      { p: "cheer", t: "手热了吗？去打一首。" }
    ];
    try { var hr = new Date().getHours(); if (hr < 5) IDLE.unshift({ p: "sleepy", t: "哈啊……这个点还在打歌吗？" }); } catch (e) {}

    var stage = document.getElementById("stage"), cast = document.getElementById("cast"), castIn = document.getElementById("cast-in");
    var vn = document.getElementById("vn"), vnLine = document.getElementById("vn-line"), actImg = document.getElementById("act"), actImg2 = document.getElementById("act2");
    var actFlip = actImg && actImg2 ? flipper(actImg, actImg2) : null, actTimers = [];
    var rig = null, baseSrc = girl ? girl.getAttribute("src") : "";
    var typeTimer = 0, hideTimer = 0, idleTimer = 0, actTimer = 0, typing = false, fullText = "";
    var beatNo = -1, idleNo = 0, inviteNo = 0, fuss = 0, clicks = [], inView = true, wantAct = "";
    var tapped = false;                     // 点过她没有：没点过，台词框里一直有个小指针在示范「点这里」
    try { tapped = !PREVIEW && localStorage.getItem("yume-tap") === "1"; } catch (e) {}
    if (tapped && win) win.classList.add("tapped");

    function pose(name) {
      if (rig) { rig.pose(name, name ? poseSrc(name) : ""); return; }
      if (!girl || body.classList.contains("no-yume")) return;      // 没有 WebGL：直接换那张静态图
      var url = name ? poseSrc(name) : baseSrc, pi = new Image();
      pi.onload = function () { girl.setAttribute("src", url); };
      pi.src = url;
    }
    function endAct() {
      actTimers.splice(0).forEach(clearTimeout); wantAct = "";
      if (win) win.classList.remove("acting", "act-jump", "act-float");
      if (actFlip) actFlip.clear();
    }
    // 整个人离地的动作：站着的那层藏起来，换成一串整框图按时间放（离地多高烤在图里），放完再把站着的那层接回来
    var ACTS = {
      jump: [[0, "a:unfold"], [110, "a:tuck2"], [230, "a:jump"], [600, "a:tuck2"], [720, "a:unfold"], [840, "a:fall"], [960, "a:touch"]],
      float: [[0, "a:upright"], [160, "a:tilt"], [320, "a:float"]]
    };
    function act(name) {
      var seq = ACTS[name];
      if (!actFlip || !win || !seq) return;
      wantAct = name;
      seq.forEach(function (st) { new Image().src = frameUrl(st[1]); });
      if (name === "jump") { new Image().src = poseSrc("land"); new Image().src = poseSrc("settle"); }
      var pi = new Image();
      pi.onload = function () {
        if (wantAct !== name) return;
        win.classList.add("acting", "act-" + name);
        seq.forEach(function (st) { actTimers.push(setTimeout(function () { actFlip.show(st[1]); }, st[0])); });
        if (name === "jump") {          // 起跳 → 最高点 → 腿放下 → 下落 → 脚尖着地 → 落定（头发还扬着）→ 头发落一半 → 站好
          pose("land");
          actTimers.push(setTimeout(function () {
            win.classList.remove("acting", "act-jump"); wantAct = ""; actFlip.clear();
            if (rig) rig.kick(.8);
          }, 1080));
          actTimers.push(setTimeout(function () { pose("settle"); }, 1250));
          actTimers.push(setTimeout(function () { pose(null); }, 1420));
        }
      };
      pi.src = frameUrl(seq[0][1]);
    }
    function rest() {                        // 这句说完了：收起台词框，回到站姿
      clearInterval(typeTimer); clearTimeout(hideTimer);
      typing = false;
      if (rig) rig.talk(false);
      if (vn) vn.classList.remove("on", "end");
      endAct(); pose(null);
      planIdle();
    }
    function finish() {                      // 字出完了
      clearInterval(typeTimer);
      typing = false;
      vnLine.textContent = fullText;
      if (rig) rig.talk(false);
      vn.classList.add("end");
      hideTimer = setTimeout(rest, tapped ? 3800 : 6500);
    }
    function show(beat) {
      if (!vn || !vnLine || body.classList.contains("no-yume")) return;
      clearInterval(typeTimer); clearTimeout(hideTimer); clearTimeout(idleTimer);
      endAct();
      if (beat.a) { pose(null); act(beat.a); } else pose(beat.p || null);
      var chars = Array.from(beat.t), k = 0;
      fullText = beat.t;
      vnLine.textContent = "";
      vn.classList.remove("end"); vn.classList.add("on");
      typing = true;
      if (rig) rig.talk(true);
      typeTimer = setInterval(function () {
        k += 1;
        vnLine.textContent = chars.slice(0, k).join("");
        if (k >= chars.length) finish();
      }, 62);
    }
    // 隔一阵自己冒一句：没人点过的时候勤一点，而且说的就是「可以点我」
    function planIdle() {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(function () {
        if (document.hidden || !inView || !win.classList.contains("live") || vn.classList.contains("on")) { planIdle(); return; }
        if (tapped) show(IDLE[idleNo++ % IDLE.length]); else show(INVITE[inviteNo++ % INVITE.length]);
      }, tapped ? rnd(22000, 34000) : 8000);
    }
    function poke() {                        // 点了她 / 点了台词框
      if (!win.classList.contains("live")) return;
      if (!tapped) {
        tapped = true; win.classList.add("tapped");
        try { if (!PREVIEW) localStorage.setItem("yume-tap", "1"); } catch (e) {}
      }
      if (typing) { finish(); return; }      // 字还在一个个出：先整句出完，再点才是下一句
      if (rig) rig.kick(.9);
      var now = Date.now();
      clicks = clicks.filter(function (t) { return now - t < 2200; });
      clicks.push(now);
      if (clicks.length >= 5) { clicks = []; show(FUSS[fuss++ % FUSS.length]); return; }
      beatNo = (beatNo + 1) % BEATS.length;
      show(BEATS[beatNo]);
      var nx = BEATS[(beatNo + 1) % BEATS.length];          // 下一张先取回来，点的时候不用等
      new Image().src = nx.a ? actSrc(nx.a) : poseSrc(nx.p);
    }

    if (PREVIEW) window.__beat = function (i) { show(BEATS[i]); };      // 预览里给检查脚本用：直接放第 i 句
    // 骨架：图到了就起；起不来（没有 WebGL）就保持静态图
    var rigCanvas = document.getElementById("rig"), firstPose = playOp ? OPS[opKind].after[0] : null;
    function startRig() {
      if (rig || !rigCanvas || !girl || !girl.naturalWidth) return;
      rig = makeRig(rigCanvas, girl, [0, 1]);
      if (rig) {
        win.classList.add("rigged");
        if (firstPose) rig.pose(firstPose, poseSrc(firstPose));
        if (!opEnded) { rig.sleep(true); whenOpEnds(function () { rig.sleep(false); }); }
      }
    }
    if (girl) { if (girl.complete) startRig(); else girl.addEventListener("load", startRig); }
    if (hover && stage && win) {
      stage.addEventListener("pointermove", function (e) {
        var r = stage.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * 2 - 1, y = (e.clientY - r.top) / r.height * 2 - 1;
        if (rig) rig.point(x, y);
      });
      stage.addEventListener("pointerleave", function () {
        if (rig) rig.point(0, 0);
      });
    }
    // 页面一滚，头发和裙摆跟着晃一下
    var lastY = window.scrollY;
    window.addEventListener("scroll", function () {
      var y = window.scrollY, d = y - lastY;
      lastY = y;
      if (rig && d) rig.kick(Math.max(-.25, Math.min(.25, d / 400)));
    }, { passive: true });
    if (cast && castIn && win && vn) {
      cast.addEventListener("click", poke);
      vn.addEventListener("click", poke);
      if ("IntersectionObserver" in window) new IntersectionObserver(function (it) { inView = it[0].isIntersecting; }, { threshold: .3 }).observe(win);
      // 开场收场时她飞过来落在这里：落定那一刻主页上的她和开场最后一帧是同一张，然后头发落一半、再站好挥手，开口打招呼
      var settle = function () {
        var v = OPS[opKind], flown = playOp && !opSkipped, wait = flown ? v.land : 650;
        var quiet = function () { return !vn.classList.contains("on") && !win.classList.contains("acting"); };
        if (!flown) pose("wave");
        else {
          setTimeout(function () { if (quiet()) pose(v.after[1]); }, wait + 170);
          setTimeout(function () { if (quiet()) { pose(v.after[2]); if (rig) rig.kick(.6); } }, wait + 340);
        }
        setTimeout(function () { win.classList.add("live"); }, wait + 700);
        setTimeout(function () {
          if (window.scrollY < 80) show(HELLO); else { pose(null); planIdle(); }
        }, wait + 1000);
      };
      whenOpEnds(settle);
    }

    // ---------- 通行证：鼠标在上面时跟着微微倾斜 ----------
    if (hover) {
      each(".pass", function (p) {
        p.addEventListener("pointermove", function (e) {
          var r = p.getBoundingClientRect();
          p.style.setProperty("--tx", ((e.clientX - r.left) / r.width * 2 - 1).toFixed(3));
          p.style.setProperty("--ty", ((e.clientY - r.top) / r.height * 2 - 1).toFixed(3));
        });
        p.addEventListener("pointerleave", function () { p.style.setProperty("--tx", "0"); p.style.setProperty("--ty", "0"); });
      });
    }

    // ---------- 点哪里，哪里出一圈「打击」 ----------
    var taps = 0;
    document.addEventListener("pointerdown", function (e) {
      if (e.button) return;
      var t = el("div", "tap");
      t.style.setProperty("--x", e.clientX + "px");
      t.style.setProperty("--y", e.clientY + "px");
      t.style.setProperty("--c", GAMES[taps++ % 4]);
      for (var a = 0; a < 6; a++) { var s = el("i"); s.style.setProperty("--a", (a * 60 + 15) + "deg"); t.appendChild(s); }
      body.appendChild(t);
      setTimeout(function () { t.remove(); }, 560);
    }, { passive: true });

    // ---------- 点站内链接：幕布先扫过来，再走 ----------
    function leave(href) {
      if (!wipe) { location.href = href; return; }
      wipe.classList.remove("back");
      wipe.classList.add("go");
      setTimeout(function () {
        Y.mark(); location.href = Y.href(href);      // 那边的页面一打开先盖着同一块幕布，再收走
      }, 780);                // 幕布盖满 + 光环画完 + 星星蹦出来
    }
    each("a[href^='/']", function (a) {
      a.addEventListener("click", function (e) {
        if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || a.target) return;
        e.preventDefault();
        leave(a.getAttribute("href"));
      });
    });
    // 从别的页面按「后退」回来：浏览器可能直接拿缓存里盖着幕布的那一页，把幕布收掉
    window.addEventListener("pageshow", function (e) { if (e.persisted && wipe) wipe.classList.remove("go", "back"); });

    // ---------- 页脚：再看一遍开场 ----------
    var replay = document.getElementById("replay");
    if (replay) {
      replay.hidden = false;
      replay.addEventListener("click", function () {
        window.scrollTo(0, 0);
        opTimers.splice(0).forEach(clearTimeout);
        root.classList.remove("op-play", "op-bye", "op-out", "op-land", "op-gone", "op-hold", "op-a", "op-b", "op-c");
        var oc = document.getElementById("op-cast");
        if (oc) { oc.style.removeProperty("--dx"); oc.style.removeProperty("--dy"); oc.style.removeProperty("--ds"); }
        opKind = KINDS[(KINDS.indexOf(opKind) + 1) % KINDS.length];              // 三套轮着看
        if (win) win.classList.remove("live");
        rest(); clearTimeout(idleTimer); pose(OPS[opKind].after[0]);
        void root.offsetWidth;
        opEnded = false; playOp = true;
        root.classList.add("op-play", "op-hold", "op-" + opKind);
        if (rig) { rig.sleep(true); whenOpEnds(function () { rig.sleep(false); }); }
        whenOpEnds(settle);
        loadOp();
      });
    }
  });
})();
