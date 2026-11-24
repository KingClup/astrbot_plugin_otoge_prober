/* 公开名片（v3.1.0）。不带任何登录状态：按地址里的短码去拿这张名片的公开内容。 */
(function () {
  "use strict";
  var Y = window.Mascot || null;
  var $ = function (id) { return document.getElementById(id); };
  var slug = (location.pathname.match(/^\/u\/([a-z0-9]{8,16})\/?$/) || [])[1] || "";
  var COLOR = { mai: "#5a95ec", chu: "#e9b94a", geki: "#ea7fb0", sdvx: "#a47de0" };
  var UNIT = { mai: "DX RATING", chu: "RATING", geki: "RATING", sdvx: "VOLFORCE" };
  var DIGITS = { mai: 0, chu: 2, geki: 3, sdvx: 3 };
  var SHORT = { mai: "舞萌", chu: "中二", geki: "音击", sdvx: "SDVX" };
  var data = null, cur = "";

  function fmt(g, v) { return v == null ? "—" : Number(v).toFixed(DIGITS[g] || 0); }
  function ago(ts) {
    var s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 90) return "刚刚更新";
    if (s < 3600) return Math.round(s / 60) + " 分钟前更新";
    if (s < 86400) return Math.round(s / 3600) + " 小时前更新";
    if (s < 86400 * 30) return Math.round(s / 86400) + " 天前更新";
    var d = new Date(ts * 1000);
    return d.getFullYear() + "/" + (d.getMonth() + 1) + "/" + d.getDate() + " 更新";
  }
  function svg(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function spark(host, g) {
    host.textContent = "";
    var h = g.hist || [];
    $("since").textContent = h.length >= 2 ? h[0][0].slice(5).replace("-", "/") + " 起，记了 " + h.length + " 天" : "";
    host.hidden = h.length < 2;
    if (h.length < 2) return;
    var W = Math.max(120, host.clientWidth), H = Math.max(48, host.clientHeight), pad = 6;
    var vals = h.map(function (x) { return x[1]; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), span = (hi - lo) || 1;
    var pts = vals.map(function (v, i) {
      return [pad + (W - pad * 2) * i / (vals.length - 1), pad + (H - pad * 2) * (1 - (v - lo) / span)];
    });
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H });
    var line = pts.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ");
    s.appendChild(svg("polygon", { class: "ar", points: pad + "," + H + " " + line + " " + (W - pad) + "," + H }));
    s.appendChild(svg("polyline", { class: "ln", points: line }));
    var last = pts[pts.length - 1];
    s.appendChild(svg("circle", { class: "dot", cx: last[0], cy: last[1], r: 4 }));
    host.appendChild(s);
  }

  function show(key) {
    var g = null;
    data.games.forEach(function (x) { if (x.game === key) g = x; });
    if (!g) return;
    cur = key;
    document.body.setAttribute("data-game", key);
    [].forEach.call($("tabs").children, function (b) { b.setAttribute("aria-selected", String(b.dataset.game === key)); });
    $("label").textContent = UNIT[key] + (g.label ? " · " + g.label : "");
    $("rating").textContent = fmt(key, g.rating);
    var d = $("delta");
    if (g.delta != null && g.delta !== 0) {
      d.hidden = false;
      d.className = "delta " + (g.delta > 0 ? "up" : "down");
      d.textContent = (g.delta > 0 ? "比上次 +" : "比上次 ") + Number(g.delta).toFixed(DIGITS[key] || 0);
    } else { d.hidden = true; }
    $("when").textContent = ago(g.ts);
    $("panel").hidden = false;
    spark($("spark"), g);
    $("img").src = g.img;
    $("img").alt = g.name + " 成绩图";
    $("shot").href = g.img;
    if (Y && Y.sky) { try { Y.sky($("sky"), [key], 6); } catch (e) { /* 没有剪影也行 */ } }
  }

  function render() {
    var name = (data.name || "").trim();
    $("who").textContent = name ? name + "的" : "这位玩家的";
    document.title = (name ? name + " 的" : "") + "成绩名片 · " + (data.bot || "AstrBot") + " 音游查分";
    var qq = data.qq || document.body.dataset.qq || "";
    if (qq) {
      var t = $("ctaText");
      t.textContent = "";
      t.append("加 " + (data.bot || "AstrBot") + "（QQ " + qq + "）好友或者把它拉进群，发 ");
      var c1 = document.createElement("code"); c1.textContent = "/网页绑定"; t.append(c1, " 绑好账号，再发 ");
      var c2 = document.createElement("code"); c2.textContent = "/名片 开"; t.append(c2, "。");
    }
    if (!data.games.length) {
      $("lede").textContent = "";
      $("empty").hidden = false;
      if (Y) Y.bust($("emptyGirl"), "think", .5);
      return;
    }
    $("lede").textContent = "最近查的成绩图和 rating 走势。主人每查一次，这里跟着更新。";
    var tabs = $("tabs");
    data.games.forEach(function (g) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "tab"; b.dataset.game = g.game; b.setAttribute("role", "tab");
      var dot = document.createElement("i"); dot.style.setProperty("--c", COLOR[g.game]);
      b.append(dot, SHORT[g.game] || g.name);
      b.addEventListener("click", function () { show(g.game); });
      tabs.appendChild(b);
    });
    tabs.hidden = data.games.length < 2;
    var newest = data.games.slice().sort(function (a, b) { return b.ts - a.ts; })[0];
    show(newest.game);
  }

  function gone() {
    $("who").textContent = "";
    $("lede").textContent = "这张名片不存在，或者主人把它关掉了。";
  }

  if (Y) { Y.ready(function () { Y.bust($("ctaGirl"), "peace", .46); }); if (Y.links) Y.links(document); }
  if (!slug) { gone(); return; }
  fetch("/api/card/" + slug, { cache: "no-store" })
    .then(function (r) { if (!r.ok) throw new Error("gone"); return r.json(); })
    .then(function (j) { data = j; render(); })
    .catch(gone);
})();
