const $ = (id) => document.getElementById(id);
let sid = null, stage = null;

const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

const UNDECIDED = ["无法确定", "说不清", "说不上", "说不出来", "不清楚", "不知道", "菜单", "候选", "给选项", "给候选", "不知道破什么", "想不出来"];
const isUndecided = (t) => UNDECIDED.some((h) => (t || "").includes(h));
const setStatus = (t) => { $("status").textContent = t; };

function appendMsg(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text;
  $("conv").appendChild(div);
  $("conv").scrollTop = $("conv").scrollHeight;
}

function fmtAmount(a) {
  if (a == null) return "";
  if (a >= 1e8) return (a / 1e8) + " 亿";
  if (a >= 1e4) return (a / 1e4) + " 万";
  return a;
}

function renderCard(card) {
  const box = $("card");
  if (!card) { box.className = "card empty"; box.textContent = "（等待抽取…）"; return; }
  box.className = "card";
  const ea = card.entry_anchor || {}, nv = card.next_verdict || {};
  const anchorTypes = ["ttm_gaap_pe", "forward_non_gaap_pe", "normalized_pe", "normalized_operating_pe",
    "normalized_fwd_gaap_pe", "p_fcf", "p_tbv", "operating_multiple_2col", "other"];
  let h = [];
  h.push('<div class="row"><label>买入逻辑（原话）</label><textarea data-field="holding_reason_raw" rows="2">' + esc(card.holding_reason_raw) + "</textarea></div>");
  h.push('<div class="row"><label>关键假设</label><div class="list">' +
    (card.key_assumptions || []).map((a) => "<div>" + esc(a.text) + "</div>").join("") + "</div></div>");
  h.push('<div class="row"><label>破局条件（两层）</label><div class="list">' +
    (card.broken_conditions || []).map((c) => {
      const tag = c.layer === "mirror" ? "镜像" : "红线";
      let extra = "";
      if (c.threshold && c.threshold.amount_usd) extra = "（≥ " + fmtAmount(c.threshold.amount_usd) + " 美元）";
      return "<div>[" + tag + "] " + esc(c.text) + extra + "</div>";
    }).join("") + "</div></div>");
  if ((card.manual_check_items || []).length)
    h.push('<div class="row"><label>人工自查项（每月）</label><div class="list">' +
      card.manual_check_items.map((m) => "<div>• " + esc(m.text) + "</div>").join("") + "</div></div>");
  h.push('<div class="row"><label>录入估值锚</label><div class="inline">' +
    '<select data-field="entry_anchor.anchor_type">' +
    anchorTypes.map((t) => '<option ' + (ea.anchor_type === t ? "selected" : "") + ">" + t + "</option>").join("") + "</select>" +
    '<input data-field="entry_anchor.anchor_value" type="number" step="0.1" value="' + (ea.anchor_value != null ? ea.anchor_value : "") + '" placeholder="倍数">' +
    '<input data-field="entry_anchor.note" value="' + esc(ea.note || "") + '" placeholder="补充"></div></div>');
  h.push('<div class="row"><label>下次裁判日</label><div class="inline">' +
    '<input data-field="next_verdict.event" value="' + esc(nv.event || "") + '" placeholder="事件">' +
    '<input data-field="next_verdict.date" value="' + esc(nv.date || "") + '" placeholder="YYYY-MM"></div></div>');
  h.push('<div class="row"><label>仓位上限档（规则查表）</label><div class="val">' + esc(card.position_cap_tier || "—") + "</div></div>");
  if ((card.open_questions || []).length)
    h.push('<div class="oq">⚠️ ' + (card.open_questions || []).map((q) => esc(q.reason)).join(" / ") + "</div>");
  box.innerHTML = h.join("");
}

function collectEdits() {
  const edits = {};
  document.querySelectorAll("#card [data-field]").forEach((el) => {
    const f = el.dataset.field, v = el.value;
    if (f.includes(".")) { const [o, k] = f.split("."); edits[o] = edits[o] || {}; edits[o][k] = v; }
    else edits[f] = v;
  });
  if (edits.entry_anchor && edits.entry_anchor.anchor_value != null && edits.entry_anchor.anchor_value !== "")
    edits.entry_anchor.anchor_value = parseFloat(edits.entry_anchor.anchor_value);
  return edits;
}

function renderMenu(menu) {
  const box = $("menu-panel");
  if (!menu) { box.className = "menu-panel hidden"; box.innerHTML = ""; return; }
  box.className = "menu-panel";
  let h = ["<h3>候选清单（勾选 → 提交）</h3>", '<div class="menu-group"><h4>A 你信什么</h4>'];
  menu.assumptions.forEach((a, i) => h.push('<label><input type="checkbox" data-ma="' + i + '"> ' + esc(a) + "</label>"));
  h.push('</div><div class="menu-group"><h4>B 破的条件</h4>');
  menu.mirrors.forEach((b, i) => h.push('<label><input type="checkbox" data-mb="' + i + '"> ' + esc(b.mirror_text) + ' <span class="dim">(对应 ' + esc(b.assumption) + ")</span></label>"));
  h.push('</div><button id="menu-submit">提交勾选</button>');
  box.innerHTML = h.join("");
  $("menu-submit").onclick = submitPicks;
}

function applyView(v) {
  stage = v.stage;
  appendMsg("assistant", v.assistant);
  renderCard(v.card);
  renderMenu(v.menu || null);
  $("error").textContent = v.error ? "⚠️ " + v.error : "";
  const statusByStage = {
    "extracted": "抽取完成 · 确认或回「无法确定」要候选菜单",
    "menu": "候选就绪 · 右侧勾选 A/B 后提交",
    "confirm_card": "卡片已渲染 · 可点改字段，确认后入库",
    "confirmed": "已落库 · 命中会单独邮件，未命中合并进简报",
  };
  setStatus(statusByStage[v.stage] || "");
  $("turn-form").classList.toggle("hidden", !(v.stage === "extracted" || v.stage === "confirm_card"));
  $("confirm-bar").classList.toggle("hidden", v.stage !== "confirm_card");
}

async function start() {
  const ticker = $("ticker").value.trim(), reason = $("reason").value.trim();
  if (!ticker || !reason) { $("error").textContent = "ticker 与理由必填"; return; }
  appendMsg("user", ticker + "：" + reason);
  $("start-btn").disabled = true; setStatus("正在抽取…（约 5–45s）");
  const r = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: "beta1", ticker, reason }) });
  const v = await r.json();
  $("start-btn").disabled = false;
  if (!r.ok) { $("error").textContent = "(" + r.status + ") " + (v.detail || JSON.stringify(v)); return; }
  sid = v.session_id;
  $("start-form").classList.add("hidden");
  $("turn-form").classList.remove("hidden");
  applyView(v);
}

async function send() {
  const text = $("msg").value.trim();
  if (!text) return;
  appendMsg("user", text); $("msg").value = "";
  setStatus(isUndecided(text) ? "正在生成候选菜单…（约 5–45s）" : "处理中…");
  await postTurn({ text });
}

async function postTurn(payload) {
  $("error").textContent = "";
  const r = await fetch("/api/session/" + sid + "/turn", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const v = await r.json();
  if (!r.ok) { $("error").textContent = "(" + r.status + ") " + (v.detail || JSON.stringify(v)); return; }
  applyView(v);
}

async function submitPicks() {
  const a = [], b = [];
  document.querySelectorAll('#menu-panel [data-ma]').forEach((el) => { if (el.checked) a.push(parseInt(el.dataset.ma)); });
  document.querySelectorAll('#menu-panel [data-mb]').forEach((el) => { if (el.checked) b.push(parseInt(el.dataset.mb)); });
  if (!a.length && !b.length) { $("error").textContent = "至少勾一条"; return; }
  appendMsg("user", "勾选 A" + JSON.stringify(a) + " B" + JSON.stringify(b));
  setStatus("正在渲染卡片…");
  await postTurn({ picks: { assumptions: a, mirrors: b } });
}

async function confirm() {
  const edits = collectEdits();
  setStatus("正在入库…");
  const r = await fetch("/api/session/" + sid + "/confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ edits }) });
  const v = await r.json();
  if (!r.ok) { $("error").textContent = "(" + r.status + ") " + (v.detail || JSON.stringify(v)); return; }
  applyView(v);
}

$("start-btn").onclick = start;
$("send-btn").onclick = send;
$("confirm-btn").onclick = confirm;
$("msg").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
$("reason").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); start(); } });
