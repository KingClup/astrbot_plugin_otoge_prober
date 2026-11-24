/* 三个网站（主页 / 绑定 / 传分）共用：看板娘骨架、动作帧、背景剪影、转场幕布、判定字。
   放在 <head> 里先于页面加载：从站内跳过来的页面要在第一帧就盖着幕布。 */
(function () {
  "use strict";
  var root = document.documentElement;
  var PREVIEW = root.hasAttribute("data-preview");      // 预览页：图片走相对路径
  var calm = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  function rnd(a, b) { return a + Math.random() * (b - a); }

  // ================= 看板娘的「骨架」=================
  // 一张全身立绘贴在一张网格上，用 WebGL 让网格的不同部位各自动：两侧的长发和裙摆摆动、上半身随呼吸起伏、
  // 头跟着鼠标微微偏、定时眨眼（眨眼是另一张只含眼睛的小图，盖在原图眼睛的位置上）。
  // 每个网格点动多少，由它在人物身上的位置算出来（下面 weights()），不需要另外的权重图。
  // 没有 WebGL 就保持原来的 <img>，只是不动。
  var IMG = PREVIEW ? "img/" : "/img/", VER = PREVIEW ? "" : "?v=305";
  function src(name) { return IMG + name + ".webp" + VER; }
  var FIG = {                     // 立绘里人物外框的位置（占整张图的比例）；build.py 会打印，换图时改这里
    top: 0.0114, bottom: 0.9886, cx: 0.5,
    // 眨眼 / 说话：各是一张只含眼睛、只含嘴的小补丁，盖在原图对应的位置上；rect 是它在立绘里的位置（blink.py 打印）
    blink: { src: src("yume-full-blink"), rect: [0.34761, 0.11531, 0.30599, 0.06214] },
    mouth: { src: src("yume-full-mouth"), rect: [0.49274, 0.15702, 0.07098, 0.025] }
  };
  // 动作差分：和定稿同一个画框、腿是定稿的腿，只有上半身和表情不一样（pose.py 出的），所以换图时下半身纹丝不动
  function poseSrc(name) { return src("yume-p-" + name); }
  // 整个人都离地的动作（跳起来、飘着）画框不一样，不走骨架，直接盖一张图
  function actSrc(name) { return src("yume-a-" + name); }
  function smooth(a, b, x) { var t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); }
  // 每个网格点属于哪个「部件」、跟多少。身体、手臂、腿的权重都是 0：不该动的不动。
  function weights(fx, fy) {      // fx：离身体中线多远（以身高为 1）；fy：从头顶 0 到鞋底 1
    // 头（连同头饰、光环、贴着头的头发）：绕脖子微微转。只算头那么宽，举到头边上的手不跟着转
    var head = smooth(.215, .15, fy) * (1 - smooth(.105, .14, fx));
    // 发梢：像钟摆，越往下摆得越多，发根不动；只算垂在身体两侧的那些
    var t = smooth(.2, .54, fy);
    var hair = smooth(.085, .125, fx) * Math.pow(t, 1.7) * (1 - smooth(.56, .6, fy));
    // 裙角：只有最下面一圈、而且只有两侧（中间有叠着的手，不动）
    var skirt = smooth(.45, .535, fy) * (1 - smooth(.535, .556, fy)) * smooth(.035, .1, fx) * (1 - smooth(.165, .2, fx));
    // 呼吸：肩和胸口很轻地起伏，到腰就没了
    var breath = smooth(.36, .25, fy) * smooth(.12, .2, fy) * (1 - smooth(.1, .14, fx));
    return [hair, skirt, breath, head];
  }
  // uA = (头转的角度, 头横移, 头纵移, 呼吸)；uH = (发梢被带动的摆幅, 裙角摆幅, 时间, 待机时「风」的大小)；uV = (v0, v1, 宽高比, 脖子的 v)
  // 待机的「风」：三个不同周期的慢正弦叠起来，越靠发梢越晚到（发梢比发根慢半拍），左右两侧、里外层相位错开——看得出在飘，但不是整片一起抖
  var VS = "attribute vec2 aUv;attribute vec4 aW;uniform vec4 uA,uV,uH;varying vec2 vUv;" +
    "void main(){vec2 p=aUv;float hair=aW.x,skirt=aW.y,breath=aW.z,head=aW.w;" +
    "vec2 d=vec2((p.x-.5)*uV.z,p.y-uV.w);float a=uA.x*head,c=cos(a),s=sin(a);" +
    "vec2 r=vec2(d.x*c-d.y*s,d.x*s+d.y*c);" +
    "p+=vec2((r.x-d.x)/uV.z,r.y-d.y)+head*vec2(uA.y/uV.z,uA.z);" +
    "float side=p.x<.5?-1.0:1.0;" +
    "float ph=uH.z-hair*.55+side*.9+(p.x-.5)*2.5;" +
    "float w=sin(ph*2.03)*.5+sin(ph*1.34+1.3)*.33+sin(ph*.86+2.1)*.17;" +
    "p.x+=(hair*(uH.x+w*uH.w)+skirt*(uH.y+w*uH.w*.3))/uV.z;" +
    "p.y-=hair*abs(w)*uH.w*.25;" +
    "p.y-=breath*uA.w;vUv=aUv;" +
    "gl_Position=vec4(p.x*2.0-1.0,1.0-(p.y-uV.x)/(uV.y-uV.x)*2.0,0.0,1.0);}";
  var FS = "precision mediump float;uniform sampler2D uTex,uBl,uMo,uTo;uniform vec4 uBR,uMR;uniform float uB,uM,uX;varying vec2 vUv;" +
    "void main(){vec4 c=texture2D(uTex,vUv);" +
    "if(uB>0.0){vec2 q=(vUv-uBR.xy)/uBR.zw;if(q.x>0.0&&q.x<1.0&&q.y>0.0&&q.y<1.0){vec4 b=texture2D(uBl,q);c=c*(1.0-b.a*uB)+b*uB;}}" +
    "if(uM>0.0){vec2 q=(vUv-uMR.xy)/uMR.zw;if(q.x>0.0&&q.x<1.0&&q.y>0.0&&q.y<1.0){vec4 b=texture2D(uMo,q);c=c*(1.0-b.a*uM)+b*uM;}}" +
    "if(uX>0.0){c=mix(c,texture2D(uTo,vUv),uX);}" +
    "gl_FragColor=c;}";
  function makeRig(canvas, img, view) {       // view = [v0, v1]：只画立绘竖直方向的这一段（比如只到大腿）
    var gl = null, two = false;
    var opts = { alpha: true, premultipliedAlpha: true, antialias: true };
    try { gl = canvas.getContext("webgl2", opts); two = !!gl; if (!gl) gl = canvas.getContext("webgl", opts); } catch (e) {}
    if (!gl || !img.naturalWidth) return null;
    function sh(type, src) { var s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; }
    var pr = gl.createProgram();
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) return null;
    gl.useProgram(pr);
    var aspect = img.naturalWidth / img.naturalHeight, fh = FIG.bottom - FIG.top;
    // 网格
    var COLS = 26, ROWS = 56, data = [], idx = [];
    for (var r = 0; r <= ROWS; r++) for (var c = 0; c <= COLS; c++) {
      var u = c / COLS, v = r / ROWS;
      var w = weights(Math.abs(u - FIG.cx) * aspect / fh, (v - FIG.top) / fh);
      data.push(u, v, w[0], w[1], w[2], w[3]);
    }
    for (r = 0; r < ROWS; r++) for (c = 0; c < COLS; c++) {
      var i = r * (COLS + 1) + c;
      idx.push(i, i + 1, i + COLS + 1, i + 1, i + COLS + 2, i + COLS + 1);
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(idx), gl.STATIC_DRAW);
    var aUv = gl.getAttribLocation(pr, "aUv"), aW = gl.getAttribLocation(pr, "aW");
    gl.enableVertexAttribArray(aUv); gl.vertexAttribPointer(aUv, 2, gl.FLOAT, false, 24, 0);
    gl.enableVertexAttribArray(aW); gl.vertexAttribPointer(aW, 4, gl.FLOAT, false, 24, 8);
    function tex(unit, image) {
      var t = gl.createTexture();
      gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, t);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      if (two) { gl.generateMipmap(gl.TEXTURE_2D); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR); }
      else gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      return t;
    }
    // 贴图：0 号位是现在这张，3 号位是正要换成的那张，4 号位只用来上传
    var texs = {}, order = [], cur = "base", to = null, want = "base", mixFrom = 0, pending = {};
    try { texs.base = tex(0, img); } catch (e) { return null; }
    function bind(unit, t) { gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, t); }
    function go(key) {
      if (to) { bind(0, texs[to]); cur = to; to = null; }       // 上一次叠化还没完：直接落定
      if (key === cur) return;
      to = key; bind(3, texs[key]); mixFrom = performance.now();
    }
    function setPose(name, url) {
      var key = name || "base";
      want = key;
      if (texs[key]) { go(key); return; }
      if (pending[key]) return;
      pending[key] = true;
      var pi = new Image();
      pi.onload = function () {
        pending[key] = false;
        try { texs[key] = tex(4, pi); } catch (e) { return; }
        order.push(key);
        // 显存里最多留 5 张动作图，再多就把最早的扔掉（图还在浏览器缓存里，要用再取）
        while (order.length > 5) { var k = order[0]; if (k === cur || k === to || k === want) break; order.shift(); gl.deleteTexture(texs[k]); delete texs[k]; }
        if (want === key) go(key);
      };
      pi.onerror = function () { pending[key] = false; };
      pi.src = url;
    }
    var U = {}; ["uA", "uH", "uV", "uTex", "uBl", "uBR", "uB", "uMo", "uMR", "uM", "uTo", "uX"].forEach(function (n) { U[n] = gl.getUniformLocation(pr, n); });
    gl.uniform1i(U.uTex, 0); gl.uniform1i(U.uBl, 1); gl.uniform1i(U.uMo, 2); gl.uniform1i(U.uTo, 3); gl.uniform1f(U.uX, 0);
    gl.uniform4f(U.uV, view[0], view[1], aspect, FIG.top + fh * .2);
    gl.uniform4f(U.uBR, 0, 0, 1, 1); gl.uniform1f(U.uB, 0);
    gl.uniform4f(U.uMR, 0, 0, 1, 1); gl.uniform1f(U.uM, 0);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.clearColor(0, 0, 0, 0);
    // 眨眼 / 说话的补丁（图取得到才用）
    var canBlink = false, canTalk = false, talking = false, mouth = 0;
    function patch(cfg, unit, rectU, ready) {
      if (!cfg) return;
      var pi = new Image();
      pi.onload = function () { try { tex(unit, pi); gl.uniform4f(rectU, cfg.rect[0], cfg.rect[1], cfg.rect[2], cfg.rect[3]); ready(); } catch (e) {} };
      pi.src = cfg.src;
    }
    patch(FIG.blink, 1, U.uBR, function () { canBlink = true; });
    patch(FIG.mouth, 2, U.uMR, function () { canTalk = true; });
    var px = 0, py = 0, tx = 0, ty = 0, raf = 0, on = false, awake = true, t0 = performance.now(), last = t0;
    // 发梢和裙角各是一根带阻尼的弹簧：头一动，它们慢半拍跟过去、过一点头再回来；没人碰就几乎静止
    var hx = 0, hv = 0, sx = 0, sv = 0, lastA = 0;
    var blinkAt = t0 + 2200, blinkDur = 0, blinkFrom = 0, twice = false;
    function size() {
      var dpr = Math.min(2, window.devicePixelRatio || 1);
      var w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
      if (w && h && (canvas.width !== w || canvas.height !== h)) { canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h); }
    }
    function frame(now) {
      raf = on ? requestAnimationFrame(frame) : 0;
      size();
      var dt = Math.min(.05, Math.max(.001, (now - last) / 1000)), t = (now - t0) / 1000;
      last = now;
      px += (tx - px) * Math.min(1, dt * 4.5); py += (ty - py) * Math.min(1, dt * 4.5);
      var b = 0, x = 0;
      if (to) {
        x = (now - mixFrom) / 150;
        if (x >= 1) { bind(0, texs[to]); cur = to; to = null; x = 0; }
      }
      gl.uniform1f(U.uX, x);
      var plain = cur === "base";            // 眨眼和嘴的补丁是照定稿那张脸做的，换了动作就不盖
      var amt = plain && !to ? 1 : .45;      // 换了动作：手可能在头边、腰上，摆动收小
      // 头：跟着鼠标转一点，自己也极慢地晃
      var ang = (px * .034 + Math.sin(t * .55) * .007) * amt;
      // 发梢：被头的转动带着（反方向甩），弹簧拉回来
      hv += -(ang - lastA) * 1.6 + (-hx * 49 - hv * 4.9) * dt;   // 约 1.1Hz、阻尼比 0.35：甩过去，回来时略过头一点
      hx += hv * dt;
      sv += -(ang - lastA) * .8 + (-sx * 100 - sv * 9) * dt;      // 裙角硬一些
      sx += sv * dt;
      lastA = ang;
      hx = Math.max(-.03, Math.min(.03, hx)); sx = Math.max(-.015, Math.min(.015, sx));
      gl.uniform4f(U.uA, ang, px * .0035 * amt, py * .0022 * amt, (Math.sin(t * 1.5) * .5 + .5) * .0022);
      var gust = .7 + .3 * Math.sin(t * .57 + Math.sin(t * .23) * 2);      // 风一阵大一阵小
      gl.uniform4f(U.uH, hx * amt, sx * amt, t, .015 * gust * amt);
      if (canBlink) {
        if (!blinkDur && now > blinkAt) { blinkDur = 230; blinkFrom = now; }
        if (blinkDur) {
          var k = (now - blinkFrom) / blinkDur;
          if (k >= 1) { blinkDur = 0; twice = !twice && Math.random() < .25; blinkAt = now + (twice ? 160 : rnd(2400, 6200)); }
          else b = k < .3 ? k / .3 : k < .55 ? 1 : 1 - (k - .55) / .45;
        }
      }
      gl.uniform1f(U.uB, plain ? b : 0);
      // 说话时嘴一张一合：两个频率叠一下，不那么机械
      var open = plain && talking && canTalk && (Math.sin(now / 62) + Math.sin(now / 37 + 1)) > -.2 ? 1 : 0;
      mouth += (open - mouth) * .45;
      gl.uniform1f(U.uM, mouth < .02 ? 0 : mouth);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawElements(gl.TRIANGLES, idx.length, gl.UNSIGNED_SHORT, 0);
    }
    var seen = true;
    function run() {
      var yes = awake && seen && !document.hidden;
      if (yes && !on) { on = true; last = performance.now(); raf = requestAnimationFrame(frame); }
      else if (!yes && on) { on = false; cancelAnimationFrame(raf); }
    }
    if ("IntersectionObserver" in window) new IntersectionObserver(function (it) { seen = it[0].isIntersecting; run(); }).observe(canvas);
    document.addEventListener("visibilitychange", run);
    canvas.addEventListener("webglcontextlost", function (e) { e.preventDefault(); awake = false; run(); });
    size(); frame(performance.now());
    return {
      point: function (x, y) { tx = x; ty = y; },
      kick: function (v) { hv += v * .047; sv += v * .03; },        // 轻轻带一下发梢和裙角
      sleep: function (yes) { awake = !yes; run(); },                 // 开场还在演的时候不画，省得抢帧
      talk: function (yes) { talking = yes; },
      pose: setPose
    };
  }
  function frameUrl(f) { var k = f.split(":"); return k[0] === "a" ? src("yume-a-" + k[1]) : k[1] ? src("yume-p-" + k[1]) : src("yume-full"); }
  function flipper(a, b) {
    var cur = a, want = "";
    function put(img, f, url) { img.classList.toggle("std", f.charAt(0) !== "a"); if (img.getAttribute("src") !== url) img.setAttribute("src", url); }
    return {
      first: function (f, ok, bad) {
        want = frameUrl(f); cur = a;
        b.classList.remove("on"); b.onload = null;
        a.onload = ok || null; a.onerror = bad || null;
        put(a, f, want); a.classList.add("on");
        if (a.complete && a.naturalWidth && ok) ok();
      },
      show: function (f) {
        var url = frameUrl(f), nx = cur === a ? b : a, swapped = false;
        want = url;
        var swap = function () { if (swapped || want !== url) return; swapped = true; nx.classList.add("on"); cur.classList.remove("on"); cur = nx; };
        nx.onload = swap;
        put(nx, f, url);
        if (nx.complete && nx.naturalWidth) swap();
      },
      clear: function () { want = ""; a.classList.remove("on"); b.classList.remove("on"); }
    };
  }
  var opFlip = null;

  // ================= 三个网站共用的小件 =================
  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }
  var SVG = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) { var e = document.createElementNS(SVG, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }

  // ---------- 看板娘的图取不取得到（公开版包里没有这些图）：取不到就整站不出人，页面照常用 ----------
  var have = 0, waiters = [];          // 0 还不知道 / 1 有 / 2 没有
  function settle(v) {
    have = v;
    if (v === 2) root.classList.add("no-yume");
    waiters.splice(0).forEach(function (fn) { fn(v === 1); });
  }
  function ready(fn) { if (have) fn(have === 1); else waiters.push(fn); }
  (function () {
    var p = new Image();
    p.onload = function () { settle(p.naturalWidth ? 1 : 2); };
    p.onerror = function () { settle(2); };
    p.src = src("yume-full");
  })();
  function poseUrl(name) { return name ? src("yume-p-" + name) : src("yume-full"); }
  // 画框的高 = 宽的百分之几（立绘 634×1400，只露到身高的 view 成）。用 padding 撑高而不是 aspect-ratio：
  // iOS 的 QQ 内置浏览器不认 aspect-ratio 里的 calc()，画框会变成整张图那么高，骨架就被竖着拉长了（v3.0.1 修）
  function ratio(view) { return (1400 * view / 634 * 100).toFixed(3) + "%"; }

  // ---------- 一个会动的看板娘 ----------
  // host 里放：定稿立绘（<img>）、骨架画布（有 WebGL 才用）、两张叠着的动作帧。
  // view = 只露到身高的几成（1 = 全身，.56 = 到裙摆，.34 = 到胸口）；露多少决定画框的高（--yp，见 ratio()）。
  function figure(host, o) {
    o = o || {};
    var v1 = o.view || 1, cur = o.pose || "", rig = null, timers = [];
    host.classList.add("yf");
    if (v1 >= 1) host.classList.add("yf-full");
    host.style.setProperty("--yp", ratio(v1));
    var img = el("img", "yf-img"), cv = el("canvas", "yf-rig"), a1 = el("img", "yf-act"), a2 = el("img", "yf-act");
    [img, a1, a2].forEach(function (i) { i.alt = ""; i.draggable = false; });
    img.decoding = "async";                     // 动作帧不异步解码：换上去那一下不能是空的
    cv.setAttribute("aria-hidden", "true");
    host.appendChild(img); host.appendChild(cv);
    if (v1 >= 1) { host.appendChild(a1); host.appendChild(a2); }
    var flip = flipper(a1, a2);
    function swap(name) {                       // 没有骨架：换一张图（先取回来再换，不闪）
      var u = poseUrl(name), pi = new Image();
      pi.onload = function () { if (cur === name) img.src = u; };
      pi.src = u;
    }
    img.addEventListener("load", function () {
      if (rig || host.classList.contains("yf-still")) return;
      host.classList.add("yf-in");
      if (!calm && !o.still) rig = makeRig(cv, img, [0, v1]);
      if (rig) { host.classList.add("yf-live"); if (cur) rig.pose(cur, poseUrl(cur)); }
      else { host.classList.add("yf-still"); if (cur) swap(cur); }
    });
    img.addEventListener("error", function () { settle(2); });
    img.src = src("yume-full");
    function pose(name) {
      name = name || "";
      if (name === cur) return;
      cur = name;
      if (rig) { rig.pose(name, poseUrl(name)); rig.kick(name ? 1 : -.6); }
      else if (host.classList.contains("yf-still")) swap(name);
    }
    function stop() { timers.splice(0).forEach(clearTimeout); flip.clear(); host.classList.remove("yf-acting"); }
    // 一串整个人都在动的帧（跳起来、走过来）：seq = [[第几毫秒, "a:jump"], …]，演完落在 endPose
    function play(seq, endPose, done) {
      stop();
      if (v1 < 1 || calm) { pose(endPose); if (done) done(); return; }
      seq.forEach(function (st) { new Image().src = frameUrl(st[1]); });
      flip.first(seq[0][1], function () { host.classList.add("yf-acting"); });
      seq.slice(1).forEach(function (st) { timers.push(setTimeout(function () { flip.show(st[1]); }, st[0])); });
      var last = seq[seq.length - 1][0];
      timers.push(setTimeout(function () { pose(endPose); }, last + 40));
      timers.push(setTimeout(function () { stop(); if (done) done(); }, last + 260));
    }
    if (o.track && window.matchMedia && window.matchMedia("(hover: hover)").matches) {
      window.addEventListener("pointermove", function (e) {
        if (!rig) return;
        var r = host.getBoundingClientRect();
        if (!r.width) return;
        rig.point(Math.max(-1, Math.min(1, (e.clientX - r.left - r.width / 2) / (window.innerWidth / 2))),
                  Math.max(-1, Math.min(1, (e.clientY - r.top - r.height * .15) / (window.innerHeight / 2))));
      }, { passive: true });
    }
    return {
      el: host, pose: pose, play: play, stop: stop,
      now: function () { return cur; },
      look: function (x, y) { if (rig) rig.point(x, y); },
      talk: function (yes) { if (rig) rig.talk(yes); },
      // 过一会儿自己换回去：比如「吓一跳」两秒后恢复
      flash: function (name, ms, back) { pose(name); timers.push(setTimeout(function () { if (cur === name) pose(back || ""); }, ms || 2200)); }
    };
  }

  // ---------- 不动的半身像（弹出的提示、顶栏这些小地方用）：就是全身动作图只露上半截 ----------
  function bust(host, name, view) {
    host.classList.add("yb");
    host.style.setProperty("--yp", ratio(view || .5));
    var img = host.querySelector("img.yb-img");
    if (!img) { img = el("img", "yb-img"); img.alt = ""; img.decoding = "async"; img.draggable = false; host.appendChild(img); }
    var cur = null;
    function pose(n) {
      n = n || "";
      if (n === cur) return;
      cur = n;
      var u = poseUrl(n), pi = new Image();
      pi.onload = function () { if (cur === n) { img.src = u; host.classList.add("yb-in"); } };
      pi.src = u;
    }
    pose(name);
    return { el: host, pose: pose };
  }

  // ---------- 背景里往下落的音符剪影 ----------
  var SYMBOLS = "<symbol id=\"n-mai-star\" viewBox=\"0 0 48 48\"><g fill=\"currentColor\"><path fill-rule=\"evenodd\" d=\"M24.00 3.00 L29.64 17.23 L44.92 18.20 L33.13 27.97 L36.93 42.80 L24.00 34.60 L11.07 42.80 L14.87 27.97 L3.08 18.20 L18.36 17.23Z M24.00 13.50 L26.94 20.95 L34.94 21.45 L28.76 26.55 L30.76 34.30 L24.00 30.00 L17.24 34.30 L19.24 26.55 L13.06 21.45 L21.06 20.95Z\"/></g></symbol><symbol id=\"n-mai-hold\" viewBox=\"0 0 48 48\"><g fill=\"currentColor\"><path fill-rule=\"evenodd\" d=\"M24 3 L36 10 L36 38 L24 45 L12 38 L12 10 Z M24 10 L18 13.5 L18 34.5 L24 38 L30 34.5 L30 13.5 Z\"/></g></symbol><symbol id=\"n-mai-touch\" viewBox=\"0 0 48 48\"><g fill=\"currentColor\"><path d=\"M24 20 L15 6 H33 Z M24 28 L33 42 H15 Z M20 24 L6 33 V15 Z M28 24 L42 15 V33 Z\"/><circle cx=\"24\" cy=\"24\" r=\"2.6\"/></g></symbol><symbol id=\"n-chu-air\" viewBox=\"0 0 48 48\"><g ><rect x=\"4\" y=\"35\" width=\"40\" height=\"7\" rx=\"2\" fill=\"currentColor\"/><path d=\"M11 28 L24 18 L37 28 M11 16 L24 6 L37 16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"4.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></g></symbol><symbol id=\"n-chu-tap\" viewBox=\"0 0 48 48\"><g fill=\"currentColor\"><path fill-rule=\"evenodd\" d=\"M6 17 h36 a3 3 0 0 1 3 3 v8 a3 3 0 0 1 -3 3 h-36 a3 3 0 0 1 -3 -3 v-8 a3 3 0 0 1 3 -3 Z M10 22.4 v3.2 h28 v-3.2 Z\"/></g></symbol><symbol id=\"n-geki-bell\" viewBox=\"0 0 48 48\"><g fill=\"currentColor\"><path fill-rule=\"evenodd\" d=\"M3.50 24.00 a20.50 20.50 0 1 0 41.00 0 a20.50 20.50 0 1 0 -41.00 0Z M15.30 31.20 a4.90 4.90 0 1 0 9.80 0 a4.90 4.90 0 1 0 -9.80 0Z M23.3 12.5 h3 v19 h-3 Z M26.3 12.5 c1.2 4.2 6.6 5 7.4 10.4 c-2.2-2.9-5.2-3.4-7.4-3.6 Z\"/></g></symbol><symbol id=\"n-geki-side\" viewBox=\"0 0 48 48\"><g fill=\"currentColor\"><rect x=\"5\" y=\"3\" width=\"5\" height=\"42\" rx=\"1.5\"/><path d=\"M13 9 L39 24 L13 39 Z\"/></g></symbol><symbol id=\"n-sdvx-fx\" viewBox=\"0 0 48 48\"><g fill=\"currentColor\"><rect x=\"3\" y=\"14\" width=\"42\" height=\"20\" rx=\"1.5\"/></g></symbol><symbol id=\"n-sdvx-bt\" viewBox=\"0 0 48 48\"><g fill=\"currentColor\"><rect x=\"13\" y=\"19\" width=\"22\" height=\"10\" rx=\"1.2\"/></g></symbol><symbol id=\"n-sdvx-laser\" viewBox=\"0 0 48 48\"><g fill=\"none\" stroke=\"currentColor\"><path d=\"M11 46 V28 H37 V2\" stroke-width=\"7.5\" stroke-linejoin=\"miter\"/></g></symbol>";
  var NOTES = ["mai-star", "chu-air", "geki-bell", "sdvx-fx", "mai-hold", "chu-tap", "geki-side", "sdvx-laser", "mai-touch", "sdvx-bt"];
  function defs() {
    if (document.getElementById("n-mai-star")) return;
    var box = el("div");
    box.innerHTML = '<svg class="ydefs" width="0" height="0" aria-hidden="true">' + SYMBOLS + "</svg>";
    document.body.appendChild(box.firstChild);
  }
  function note(name, cls) {            // 单独要一个剪影（按钮上、判定字旁边）
    defs();
    var n = svg("svg", { viewBox: "0 0 48 48", "class": "ynote g-" + name.split("-")[0] + (cls ? " " + cls : ""), "aria-hidden": "true" });
    n.appendChild(svg("use", { href: "#n-" + name }));
    return n;
  }
  function sky(host, games, count) {
    host.classList.add("ysky");
    host.textContent = "";
    if (calm) return;
    var names = NOTES.filter(function (n) { return !games || games.indexOf(n.split("-")[0]) >= 0; });
    if (!names.length) return;
    count = count || (window.innerWidth < 720 ? 8 : 14);
    for (var i = 0; i < count; i++) {
      var name = names[i % names.length], n = note(name);
      var dur = rnd(20, 38), r0 = rnd(-24, 24), spin = name === "mai-star" ? rnd(120, 240) : rnd(-36, 36);
      n.style.setProperty("--x", rnd(1, 96).toFixed(1) + "%");
      n.style.setProperty("--s", Math.round(rnd(16, 32)) + "px");
      n.style.setProperty("--o", rnd(.16, .4).toFixed(2));
      n.style.setProperty("--d", dur.toFixed(1) + "s");
      n.style.setProperty("--dl", (-rnd(0, dur)).toFixed(1) + "s");
      n.style.setProperty("--r0", r0.toFixed(0) + "deg");
      n.style.setProperty("--r1", (r0 + spin).toFixed(0) + "deg");
      host.appendChild(n);
    }
  }

  // ---------- 站和站之间：千鸟格幕布扫过来，光环一笔画出来，到了那边幕布再收走 ----------
  var wipeEl = null, WIPE_KEY = "yume-wipe";
  function wipe() {
    if (wipeEl) return wipeEl;
    wipeEl = document.getElementById("wipe");
    if (wipeEl) return wipeEl;
    wipeEl = el("div", "ywipe");
    wipeEl.setAttribute("aria-hidden", "true");
    wipeEl.appendChild(el("i")); wipeEl.appendChild(el("i"));
    var h = svg("svg", { "class": "ywipe-halo", viewBox: "0 0 160 64" });
    h.appendChild(svg("ellipse", { "class": "rip", cx: 80, cy: 32, rx: 70, ry: 23 }));
    h.appendChild(svg("ellipse", { "class": "ring", cx: 80, cy: 32, rx: 70, ry: 23, pathLength: 100 }));
    h.appendChild(svg("path", { "class": "star", d: "M138 4 Q139.8 15.2 151 17 Q139.8 18.8 138 30 Q136.2 18.8 125 17 Q136.2 15.2 138 4Z" }));
    wipeEl.appendChild(h);
    document.body.appendChild(wipeEl);
    return wipeEl;
  }
  function href(h) {                    // 预览里三个站是三个静态文件
    if (!PREVIEW) return h;
    var p = h.split("#")[0].split("?")[0];
    return p === "/bind" ? "bind.html" : p === "/scores" ? "scores.html" : p === "/" ? "index.html" : h;
  }
  function mark() { try { sessionStorage.setItem(WIPE_KEY, String(Date.now())); } catch (e) {} }
  function leave(to) {
    to = href(to);
    if (calm) { location.href = to; return; }
    var w = wipe();
    w.classList.remove("back"); void w.offsetWidth; w.classList.add("sweep");
    mark();
    setTimeout(function () { location.href = to; }, 780);
  }
  function links(scope) {               // 站内链接（/ 开头、不开新窗口的）都走幕布
    Array.prototype.forEach.call((scope || document).querySelectorAll("a[href^='/']"), function (a) {
      a.addEventListener("click", function (e) {
        if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || a.target) return;
        e.preventDefault();
        leave(a.getAttribute("href"));
      });
    });
  }
  // 是从站内跳过来的：这一页先盖着幕布（yume.css 里 .yume-arrive 管），页面好了再收走
  var arriving = false;
  try {
    var at = Number(sessionStorage.getItem(WIPE_KEY) || 0);
    sessionStorage.removeItem(WIPE_KEY);
    arriving = !calm && at > 0 && Date.now() - at < 6000;
  } catch (e) {}
  if (arriving && !root.hasAttribute("data-own-wipe")) root.classList.add("yume-arrive");
  else arriving = false;
  document.addEventListener("DOMContentLoaded", function () {
    if (!arriving) return;
    var w = wipe();
    w.classList.add("hold");
    requestAnimationFrame(function () { requestAnimationFrame(function () {
      root.classList.remove("yume-arrive");
      w.classList.remove("hold"); w.classList.add("back");
      setTimeout(function () { w.classList.remove("back"); }, 620);
    }); });
  });
  // 按「后退」回来：浏览器可能直接拿缓存里盖着幕布的那一页
  window.addEventListener("pageshow", function (e) { if (e.persisted && wipeEl) wipeEl.classList.remove("go", "sweep", "back", "hold"); });

  // ---------- 判定字：一条千鸟格的带子扫过来，金字一个个落下，星星蹦出去 ----------
  var GAME_COLORS = ["#2878eb", "#f0b429", "#ec5096", "#8a46dc"];
  function judge(text, o) {
    o = o || {};
    var j = el("div", "yjudge" + (o.small ? " small" : ""));
    j.setAttribute("aria-hidden", "true");
    if (o.top) j.style.setProperty("top", o.top);
    var band = el("div", "yjudge-band"), word = el("div", "yjudge-word");
    text.split("").forEach(function (ch, i) {
      var s = el("span");
      s.textContent = ch === " " ? " " : ch;
      s.style.setProperty("--i", String(i));
      word.appendChild(s);
    });
    band.appendChild(word);
    if (o.sub) { var sub = el("div", "yjudge-sub"); sub.textContent = o.sub; band.appendChild(sub); }
    j.appendChild(band);
    if (!calm) {
      var colors = o.colors || GAME_COLORS;
      for (var k = 0; k < 10; k++) {
        var st = el("i", "yjudge-star");
        st.style.setProperty("--a", (k * 36 + rnd(-10, 10)).toFixed(0) + "deg");
        st.style.setProperty("--r", Math.round(rnd(90, 190)) + "px");
        st.style.setProperty("--c", colors[k % colors.length]);
        st.style.setProperty("--dl", (.34 + k * .018).toFixed(2) + "s");
        j.appendChild(st);
      }
    }
    document.body.appendChild(j);
    setTimeout(function () { j.remove(); }, o.ms || 1900);
    return j;
  }

  window.Mascot = {
    PREVIEW: PREVIEW, calm: calm, src: src, poseUrl: poseUrl, frameUrl: frameUrl, flipper: flipper, makeRig: makeRig,
    ready: ready, figure: figure, bust: bust, sky: sky, note: note, leave: leave, links: links, mark: mark, href: href,
    judge: judge, rnd: rnd
  };
})();
