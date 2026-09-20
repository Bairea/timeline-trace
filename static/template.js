/* 模板编辑页
 *
 * 设计文档 §6.3：模板块不能随手删，须进这一页，刻意多一道手续。
 * 因此本页的取舍与对照页**刻意不同**：
 *
 *   对照页：真删除 + 5 秒撤销，不弹确认框。
 *           理由是一天要删多次，模态框是纯负担；容错靠可逆。
 *   本页  ：删除走二次确认，且不提供撤销。
 *           理由是模板是基准线——删掉一格，全部历史日报的对照结果
 *           都会跟着变，影响面不是「这一块」而是「所有天」。
 *           可逆性在这里不够用，因为用户按撤销时已经看不出影响面了。
 *
 * 其余编辑（改名、调时间、换类别）即时生效，不弹框：改错了再改回来
 * 即可，且每次都只影响一个格子。
 */
'use strict';

const DAY_MIN = 1440;

/** 与模板种子数据一致的类别候选（设计文档 §3 注释里列的六个） */
const CATEGORIES = ['睡眠', '身体锚点', '情绪稳定', '项目推进', '通勤', '事务'];

const state = {
  templates: [],
  tpl: null,
  blocks: [],
  pendingDelete: null,
};

function $(id) { return document.getElementById(id); }

function fmtMin(m) {
  if (m === null || m === undefined) return '';
  const h = Math.floor(m / 60) % 24, mi = m % 60;
  return `${String(h).padStart(2, '0')}:${String(mi).padStart(2, '0')}`;
}

/** 分钟数 → HH:MM。跨零点（>1440）标注「次日」，避免读成 30:30 这种非法值。 */
function fmtMinCross(m) {
  if (m === null || m === undefined) return '';
  if (m > DAY_MIN) return `次日 ${fmtMin(m)}`;
  return fmtMin(m);
}

function durationLabel(start, end) {
  if (end <= start) return '—';
  const d = end - start;
  const h = Math.floor(d / 60), mi = d % 60;
  return h ? `${h}h${mi ? String(mi).padStart(2, '0') : ''}` : `${mi}min`;
}

/** 'HH:MM' → 分钟数。接受 8:5 / 0805 / 8.5 等写法，与快速记录框保持同一手感。 */
function parseTime(text) {
  const s = String(text).trim()
    .replace(/[０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
    .replace(/[：]/g, ':').replace(/[。．]/g, '.');
  if (!s) return null;
  let h, mi;
  const m = s.match(/^(\d{1,2})[:.](\d{1,2})$/);
  if (m) { h = +m[1]; mi = +m[2]; }
  else if (/^\d{3,4}$/.test(s)) {
    h = s.length === 3 ? +s.slice(0, 1) : +s.slice(0, 2);
    mi = s.length === 3 ? +s.slice(1) : +s.slice(2);
  } else return null;
  if (h > 24 || mi > 59) return null;
  const total = h * 60 + mi;
  return total > DAY_MIN ? null : total;
}

const api = {
  async req(method, url, body) {
    const opt = { method, headers: {} };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    const r = await fetch(url, opt);
    if (r.status === 401) {
      window.location.href = '/static/login.html';
      throw new Error('未授权');
    }
    const data = r.headers.get('content-type')?.includes('json')
      ? await r.json() : await r.text();
    return { ok: r.ok, status: r.status, data };
  },
  templates() { return this.req('GET', '/api/templates'); },
  blocks(tid) { return this.req('GET', `/api/templates/${tid}/blocks`); },
  addBlock(tid, fields) { return this.req('POST', `/api/templates/${tid}/blocks`, fields); },
  updateBlock(id, fields) { return this.req('PUT', `/api/template-blocks/${id}`, fields); },
  removeBlock(id) { return this.req('DELETE', `/api/template-blocks/${id}`); },
};

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function showToast(text) {
  $('toastText').textContent = text;
  $('toast').hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { $('toast').hidden = true; }, 4000);
}

function flashError(msg) {
  $('toastText').innerHTML = msg;
  $('toast').hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { $('toast').hidden = true; }, 6000);
}

/** 服务端校验失败时把 detail 原样透出——猜错原因比报错本身更费时间。 */
function errDetail(r) {
  const d = r.data?.detail;
  return Array.isArray(d) ? d.map(x => x.msg).join('；') : (d || `HTTP ${r.status}`);
}

// ---------- 渲染 ----------
function render() {
  const list = $('blockList');
  if (!state.blocks.length) {
    list.innerHTML = '<div class="empty">模板里还没有时间块。点右上角「新增时间块」开始。</div>';
    $('catChips').innerHTML = '';
    return;
  }
  const rows = state.blocks.map(b => {
    const catOpts = ['<option value="">未分类</option>']
      .concat(CATEGORIES.map(c =>
        `<option value="${c}"${c === b.category ? ' selected' : ''}>${c}</option>`))
      .join('');
    return `<div class="block-row" data-id="${b.id}">
      <input class="bt" data-field="start_min" value="${fmtMin(b.start_min)}"
             title="开始时间，可写 08:30 / 0830 / 8.5">
      <span class="dash">–</span>
      <input class="bt" data-field="end_min" value="${fmtMin(b.end_min)}"
             title="结束时间。跨零点填大于开始的时刻即可，例如睡觉填 06:30">
      <span class="dur">${durationLabel(b.start_min, b.end_min)}</span>
      <input class="bn" data-field="name" value="${escapeHtml(b.name)}"
             title="块名。统计的优先级判定依赖它，改名会改变统计口径">
      <select class="bc" data-field="category">${catOpts}</select>
      <button class="row-del" title="删除这个模板块">删除</button>
    </div>`;
  }).join('');

  list.innerHTML = `<div class="block-list-head">
      <span>开始</span><span></span><span>结束</span><span>时长</span>
      <span>名称</span><span>类别</span><span></span>
    </div>${rows}`;

  renderCatChips();
  bindRows();
}

/** 未用到任何类别的说明——类别是统计口径的锚点，留空会在统计里静默漏掉。 */
function renderCatChips() {
  const used = new Set(state.blocks.map(b => b.category).filter(Boolean));
  const missing = CATEGORIES.filter(c => !used.has(c));
  const chips = CATEGORIES.map(c =>
    `<span class="chip" style="${used.has(c) ? '' : 'opacity:.45'}">${c}</span>`).join('');
  $('catChips').innerHTML = chips
    + (missing.length
      ? `<span class="chip" style="border-style:dashed">未使用：${missing.join('、')}</span>`
      : '');
}

function bindRows() {
  for (const row of document.querySelectorAll('.block-row')) {
    const id = Number(row.dataset.id);

    const startEl = row.querySelector('[data-field="start_min"]');
    const endEl = row.querySelector('[data-field="end_min"]');
    const durEl = row.querySelector('.dur');

    // 起止时间即时预览时长，不等保存
    for (const el of [startEl, endEl]) {
      el.addEventListener('input', () => {
        const s = parseTime(startEl.value), e = parseTime(endEl.value);
        durEl.textContent = (s !== null && e !== null && e > s)
          ? durationLabel(s, e) : '—';
      });
      el.addEventListener('keydown', ev => {
        if (ev.key === 'Enter') { ev.preventDefault(); el.blur(); }
      });
      el.addEventListener('blur', () => commitTimes(row, id));
    }

    const nameEl = row.querySelector('[data-field="name"]');
    nameEl.addEventListener('keydown', ev => {
      if (ev.key === 'Enter') { ev.preventDefault(); nameEl.blur(); }
    });
    nameEl.addEventListener('blur', async () => {
      const v = nameEl.value.trim();
      const cur = state.blocks.find(b => b.id === id);
      if (!cur || v === cur.name) { nameEl.value = cur ? cur.name : v; return; }
      if (!v) { nameEl.value = cur.name; flashError('名称不能为空'); return; }
      await save(id, { name: v });
    });

    row.querySelector('[data-field="category"]').addEventListener('change', async ev => {
      await save(id, { category: ev.target.value || null });
    });

    row.querySelector('.row-del').addEventListener('click', () => askDelete(id));
  }
}

/** 起止时间一起提交：只提交一个字段时，服务端无法判断另一个是否合法。 */
async function commitTimes(row, id) {
  const cur = state.blocks.find(b => b.id === id);
  if (!cur) return;
  const startEl = row.querySelector('[data-field="start_min"]');
  const endEl = row.querySelector('[data-field="end_min"]');
  const s = parseTime(startEl.value), e = parseTime(endEl.value);

  if (s === null || e === null) {
    startEl.value = fmtMin(cur.start_min);
    endEl.value = fmtMin(cur.end_min);
    flashError(`时间格式看不懂：<code>${escapeHtml(startEl.value || endEl.value)}</code>。可写 08:30 / 0830 / 8.5`);
    return;
  }
  if (s === cur.start_min && e === cur.end_min) return;

  // 跨零点：结束小于开始时，按次日算（22:40 → 06:30 = 1360 → 1830）
  let end = e;
  if (end <= s) end += DAY_MIN;

  const r = await api.updateBlock(id, { start_min: s, end_min: end });
  if (!r.ok) {
    startEl.value = fmtMin(cur.start_min);
    endEl.value = fmtMin(cur.end_min);
    flashError(`保存失败：${escapeHtml(errDetail(r))}`);
    return;
  }
  await load();
}

async function save(id, fields) {
  const r = await api.updateBlock(id, fields);
  if (!r.ok) { flashError(`保存失败：${escapeHtml(errDetail(r))}`); await load(); return; }
  await load();
}

// ---------- 删除（二次确认，无撤销）----------
function askDelete(id) {
  const b = state.blocks.find(x => x.id === id);
  if (!b) return;
  state.pendingDelete = id;
  $('confirmTitle').textContent = `删除「${b.name}」？`;
  $('confirmText').innerHTML =
    `这一格将从比对基准线中移除，<strong>所有历史日报的对照结果都会重新计算</strong>。`
    + `删除不能撤销。`;
  $('confirm').hidden = false;
  $('confirmOk').focus();
}

async function doDelete() {
  const id = state.pendingDelete;
  $('confirm').hidden = true;
  state.pendingDelete = null;
  if (id == null) return;
  const r = await api.removeBlock(id);
  if (!r.ok) { flashError(`删除失败：${escapeHtml(errDetail(r))}`); return; }
  await load();
  showToast('已删除该模板块');
}

// ---------- 新增 ----------
async function addBlock() {
  if (!state.tpl) return;
  // 起止取「上一块结束后 30 分钟」，比固定塞 00:00 更接近真实意图
  const last = state.blocks[state.blocks.length - 1];
  const start = last ? Math.min(last.end_min, DAY_MIN - 30) : 0;
  const r = await api.addBlock(state.tpl.id, {
    start_min: start, end_min: Math.min(start + 30, DAY_MIN), name: '新时间块',
  });
  if (!r.ok) { flashError(`新增失败：${escapeHtml(errDetail(r))}`); return; }
  await load();
  // 新增后把焦点落到名称上，省一次点击
  const row = document.querySelector(`.block-row[data-id="${r.data.id}"] .bn`);
  if (row) { row.focus(); row.select(); }
}

// ---------- 加载 ----------
async function load() {
  const r = await api.templates();
  if (!r.ok) { $('blockList').innerHTML = '<div class="empty">模板加载失败</div>'; return; }
  state.templates = r.data;
  if (!state.templates.length) {
    $('blockList').innerHTML = '<div class="empty">没有模板</div>';
    return;
  }
  state.tpl = state.templates.find(x => x.is_default) || state.templates[0];
  $('tplName').textContent = state.tpl.name;
  $('tplDesc').textContent = state.tpl.description || '';

  const b = await api.blocks(state.tpl.id);
  if (!b.ok) { $('blockList').innerHTML = '<div class="empty">模板块加载失败</div>'; return; }
  state.blocks = b.data;
  render();
}

function boot() {
  $('addBlock').onclick = addBlock;
  $('confirmCancel').onclick = () => { $('confirm').hidden = true; state.pendingDelete = null; };
  $('confirmOk').onclick = doDelete;
  $('toastClose').onclick = () => { $('toast').hidden = true; };
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !$('confirm').hidden) {
      $('confirm').hidden = true; state.pendingDelete = null;
    }
  });
  load();
}

document.addEventListener('DOMContentLoaded', boot);
