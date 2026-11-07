const bridge = window.AstrBotPluginView;
const $ = (id) => document.getElementById(id);

const SAMPLES = [
  "帮我查一下中二国际服b30",
  "中二b30",
  "看看我中二最近打了啥",
  "我中二rating多少了",
  "查下中二 Aleph-0 的成绩",
  "帮我查一下maimai b50",
  "今天去打中二了好累",
];

function setMsg(el, text, ok) {
  el.textContent = text;
  el.className = "msg " + (ok ? "ok" : "err");
}

function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString();
}

async function busy(btn, fn) {
  btn.disabled = true;
  try {
    return await fn();
  } finally {
    btn.disabled = false;
  }
}

async function loadStatus() {
  const s = await bridge.apiGet("chu/status");
  const v = s.version_info || {};
  $("theme-ver").textContent =
    `当前版本：${v.current ?? "未知"}` +
    (v.override && v.override !== "auto" ? `（手动指定；曲库推断为 ${v.detected ?? "?"}）` : "（根据曲库自动判断）");
  const cl = $("credits");
  cl.innerHTML = "";
  for (const c of s.credits || []) {
    const li = document.createElement("li");
    const b = document.createElement("b");
    b.textContent = c.name;
    li.append(b, document.createTextNode(` — ${c.what}  `));
    const code = document.createElement("code");
    code.textContent = c.url;
    li.appendChild(code);
    cl.appendChild(li);
  }
  $("meta").textContent =
    `v${s.version || "?"} · 自然语言：按群开关（在「总览」页设置）` +
    ` · 白名单：${(s.allowed_qq || []).length ? s.allowed_qq.join(", ") : "所有人"}`;
  const r = s.refresh || {};
  const last = r.last ? `上次刷新 ${fmtTime(r.last.at)}（${r.last.songdb}；${r.last.jackets}）` : "本次启动后还没刷新过";
  $("songdb").textContent =
    (s.songdb.count ? `${s.songdb.source}，${s.songdb.count} 首` : "尚未加载（第一次查询时自动下载）") +
    ` · 曲绘索引 ${s.jackets} 首\n` +
    (r.enabled ? `每日刷新：${r.time}，下次 ${r.next ?? "（启动中）"}` : "每日刷新：已关闭") + `\n${last}`;

  const tbody = $("bindings");
  tbody.innerHTML = "";
  if (!s.bindings.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="muted">还没有绑定</td></tr>';
    return;
  }
  for (const b of s.bindings) {
    const tr = document.createElement("tr");
    for (const v of [b.qq, b.name ?? "（未验证）", fmtTime(b.bound_at), ""]) {
      const td = document.createElement("td");
      td.textContent = v;
      tr.appendChild(td);
    }
    const cell = tr.lastElementChild;
    for (const [what, label] of [["profile", "资料"], ["recent", "最近"], ["b50", "B50"]]) {
      const btn = document.createElement("button");
      btn.className = "small secondary";
      btn.textContent = label;
      btn.onclick = () => runTest(btn, b.qq, what);
      cell.appendChild(btn);
    }
    const del = document.createElement("button");
    del.className = "small danger";
    del.textContent = "解绑";
    del.onclick = () => busy(del, async () => {
      if (!confirm(`确定解绑 ${b.qq}？`)) return;
      await bridge.apiPost("chu/unbind", { qq: b.qq });
      await loadStatus();
    });
    cell.appendChild(del);
    tbody.appendChild(tr);
  }
}

async function runTest(btn, qq, what) {
  const out = $("test-out");
  out.hidden = false;
  out.textContent = "查询中…（第一次会先登录 CHUNITHM-NET 并下载曲库）";
  await busy(btn, async () => {
    try {
      const r = await bridge.apiPost("chu/test", { qq, what });
      out.textContent = r.text;
    } catch (e) {
      out.textContent = "失败：" + e.message;
    }
  });
}

$("bind-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = $("bind-msg");
  const clalInput = $("bind-clal");
  await busy($("bind-btn"), async () => {
    setMsg(msg, "登录验证中…", true);
    try {
      const r = await bridge.apiPost("chu/bind", {
        qq: $("bind-qq").value.trim(),
        clal: clalInput.value,
        verify: !$("bind-noverify").checked,
      });
      setMsg(msg, r.message, true);
      clalInput.value = "";
      await loadStatus();
    } catch (e) {
      setMsg(msg, e.message, false);
    }
  });
});

$("intent-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const out = $("intent-out");
  out.hidden = false;
  out.textContent = "识别中…";
  try {
    const r = await bridge.apiPost("chu/intent", { text: $("intent-text").value });
    const names = {
      profile: "查资料", recent: "查最近记录", b50: "B50 图片", b50_text: "B50 文字",
      song: "查单曲", help: "帮助", none: "不处理（交给机器人正常聊天）",
    };
    out.textContent =
      `→ ${names[r.action] || r.action}${r.query ? `：${r.query}` : ""}\n` +
      `游戏：${r.game}　识别方式：${r.source}` +
      (r.raw ? `\n模型原始输出：${r.raw}` : "");
  } catch (e) {
    out.textContent = "失败：" + e.message;
  }
});

for (const s of SAMPLES) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = s;
  b.onclick = () => {
    $("intent-text").value = s;
    $("intent-form").requestSubmit();
  };
  $("intent-samples").appendChild(b);
}

$("songdb-btn").addEventListener("click", (ev) =>
  busy(ev.target, async () => {
    const m = $("songdb-msg");
    setMsg(m, "下载中…", true);
    try {
      const r = await bridge.apiPost("chu/songdb/refresh", {});
      setMsg(m, `完成：${r.source}，${r.count} 首；${r.jackets ?? ""}`, true);
      await loadStatus();
    } catch (e) {
      setMsg(m, e.message, false);
    }
  }),
);

// ---------- B50 主题 ----------
function setPreview(id, info, emptyText) {
  const el = $(id);
  el.innerHTML = "";
  if (info && info.preview) {
    const img = document.createElement("img");
    img.src = info.preview;
    el.appendChild(img);
    if (info.from) el.title = `来自 themes/${info.from}`;
  } else if (info && info.ok === false) {
    el.textContent = "上传了，但切分失败";
  } else {
    el.textContent = emptyText;
  }
}

async function loadTheme() {
  const t = await bridge.apiGet("chu/theme");
  setPreview("pv-digits", t.digits, "未上传（使用插件自绘的段位色数字）");
  setPreview("pv-bg", t.bg, "未上传（使用自绘背景）");
  setPreview("pv-logo", t.logo, "未设置（每日更新时会自动从官网获取）");
}

for (const input of document.querySelectorAll("input[type=file][data-kind]")) {
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    const kind = input.dataset.kind;
    let scope = input.dataset.scope;
    if (kind === "bg" && $("bg-default").checked) scope = "default";
    const msg = $("theme-msg");
    setMsg(msg, "上传中…", true);
    try {
      const r = await bridge.upload(`chu/theme/upload/${kind}/${scope}`, file);
      setMsg(msg, `已保存：${r.saved}`, true);
      await loadTheme();
      await runPreview(); // 换了素材就直接看效果
    } catch (e) {
      setMsg(msg, e.message, false);
    }
    input.value = "";
  });
}

$("logo-fetch").addEventListener("click", (ev) =>
  busy(ev.target, async () => {
    const box = $("logo-cands");
    const msg = $("theme-msg");
    box.innerHTML = "";
    setMsg(msg, "正在从官网抓取 logo 候选…", true);
    try {
      const r = await bridge.apiPost("chu/theme/logo/candidates", {});
      if (!r.candidates.length) {
        setMsg(msg, "官网首页没找到 logo 图片，可以手动上传", false);
        return;
      }
      setMsg(msg, `找到 ${r.candidates.length} 张（当前版本：${r.version ?? "?"}），点「使用」保存为该版本的 logo`, true);
      for (const c of r.candidates) {
        const div = document.createElement("div");
        div.className = "cand";
        const img = document.createElement("img");
        img.src = c.preview;
        const url = document.createElement("div");
        url.className = "url";
        url.textContent = `${c.w}×${c.h}  ${c.url}`;
        const btn = document.createElement("button");
        btn.className = "small";
        btn.textContent = "使用";
        btn.onclick = () => busy(btn, async () => {
          try {
            await bridge.apiPost("chu/theme/logo/use", { url: c.url });
            setMsg(msg, "已保存", true);
            await loadTheme();
            box.innerHTML = "";
            await runPreview();
          } catch (e) {
            setMsg(msg, e.message, false);
          }
        });
        div.append(img, url, btn);
        box.appendChild(div);
      }
    } catch (e) {
      setMsg(msg, e.message, false);
    }
  }),
);

// 图片大小滑块：200 KB … 8 MB，最右 = 原图（0）
const SIZE_STEPS = [200, 300, 500, 800, 1000, 1500, 2000, 3000, 4000, 5000, 8000, 0];
const fmtKB = (kb) => (kb === 0 ? "原图" : kb >= 1000 ? `${(kb / 1000).toFixed(kb % 1000 ? 1 : 0)} MB` : `${kb} KB`);
const fmtSize = (kb) => (kb >= 1024 ? `${(kb / 1024).toFixed(2)} MB` : `${kb} KB`);
const stepOf = (kb) => {
  const i = SIZE_STEPS.indexOf(kb);
  if (i >= 0) return i;
  if (!kb) return SIZE_STEPS.length - 1;
  let best = 0;
  SIZE_STEPS.forEach((v, j) => { if (v && Math.abs(v - kb) < Math.abs(SIZE_STEPS[best] - kb)) best = j; });
  return best;
};
let sizeInit = false;

function showPreview(r) {
  const img = $("preview-img");
  img.src = r.image;
  $("preview-wrap").hidden = false;
  const s = r.size || {};
  $("size-info").textContent =
    `实际 ${fmtSize(s.kb ?? 0)} · 画质 ${s.quality ?? "?"} · ${s.width}×${s.height}` +
    (r.orig_kb != null ? ` · 原图 ${fmtSize(r.orig_kb)}` : "");
  $("size-saved").textContent = `当前发送设置：${fmtKB(r.saved_max_kb ?? 3000)}`;
}

async function runPreview() {
  const m = $("preview-msg");
  setMsg(m, "生成中…（第一次会下载 50 张曲绘，约十几秒）", true);
  try {
    const body = sizeInit ? { max_kb: SIZE_STEPS[+$("size-range").value] } : {};
    const r = await bridge.apiPost("chu/theme/preview", body);
    if (!sizeInit) {
      $("size-range").value = stepOf(r.max_kb);
      $("size-target").textContent = fmtKB(r.max_kb);
      sizeInit = true;
    }
    showPreview(r);
    setMsg(m, `版本 ${r.version ?? "?"} · ${r.jackets}`, true);
  } catch (e) {
    setMsg(m, e.message, false);
  }
}

$("size-range").addEventListener("input", () => {
  $("size-target").textContent = fmtKB(SIZE_STEPS[+$("size-range").value]);
});
$("size-range").addEventListener("change", async () => {
  const kb = SIZE_STEPS[+$("size-range").value];
  $("size-info").textContent = "压缩中…";
  try {
    showPreview(await bridge.apiPost("chu/theme/preview/size", { max_kb: kb }));
  } catch (e) {
    $("size-info").textContent = e.message;
  }
});
$("size-save").addEventListener("click", (ev) =>
  busy(ev.target, async () => {
    const kb = SIZE_STEPS[+$("size-range").value];
    try {
      const r = await bridge.apiPost("chu/theme/size", { max_kb: kb });
      $("size-saved").textContent = `已保存：以后发送的 B50 图片 ≤ ${fmtKB(r.saved_max_kb)}`;
    } catch (e) {
      $("size-saved").textContent = e.message;
    }
  }),
);

$("preview-btn").addEventListener("click", (ev) => busy(ev.target, runPreview));
$("preview-open").addEventListener("click", () => {
  const src = $("preview-img").src;
  if (!src) return;
  const w = window.open();
  if (w) w.document.write(`<img src="${src}" style="max-width:100%">`);
});

await bridge.ready();
try {
  await loadStatus();
} catch (e) {
  $("meta").textContent = "加载失败：" + e.message;
}
try {
  await loadTheme(); // 状态接口出错也不影响主题区
} catch (e) {
  setMsg($("theme-msg"), "主题加载失败：" + e.message, false);
}
