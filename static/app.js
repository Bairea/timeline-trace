/* 时间线对照 —— 原生 JS 单页
 *
 * 分层：
 *   1. API 层      —— 所有后端交互集中于此，便于出错时定位
 *   2. 渲染层      —— 按分钟数换算像素，纯展示
 *   3. 交互层      —— 删除 / 改名 / 微调 / 拖动
 *
 * 时间一律用「自 00:00 起的分钟数」整数表示，与后端一致。
 */
'use strict';

// ---------- 常量 ----------
const DAY_MIN = 1440;
const SNAP_MIN = 5;              // 拖动吸附粒度
const REWARD_UNDO_MS = 5000;

// 缩放用「倍率」语义：1 = 基准密度。基准值是每小时 72px，
// 即 24 小时铺开 1728px。
//
// 这里曾经出过一个单位错误：state.zoom 被当成「每小时像素数」用，
// 但默认值写的是 1（倍率语义），于是轴高算成 1×24 = 24px，
// 24 小时全挤成一坨。现在统一为倍率，像素换算只在 hourPx() 里做。
const BASE_HOUR_PX = 72;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;
const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];
const ZOOM_DEFAULT = 1;

// ---------- 状态 ----------
const state = {
  date: todayISO(),
  templateName: '',
  tplBlocks: [],
  rows: [],            // 对照结果
  actualRows: [],      // 实际块（数据库行，含未闭合）
  deleted: null,       // { id, name, timer }
  selectedId: null,
  drag: null,
  zoom: ZOOM_DEFAULT,  // 倍率，1 = BASE_HOUR_PX
};

// ---------- 工具 ----------
function todayISO() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function fmtMin(m) {
  if (m === null || m === undefined) return '';
  const h = Math.floor(m / 60) % 24, mi = m % 60;
  return `${String(h).padStart(2, '0')}:${String(mi).padStart(2, '0')}`;
}

function snap(m) {
  return Math.round(m / SNAP_MIN) * SNAP_MIN;
}

function $(id) { return document.getElementById(id); }

/** 当前每小时占多少像素。几何换算的唯一入口。 */
function hourPx() { return BASE_HOUR_PX * state.zoom; }

/** 当前每分钟占多少像素。 */
function pxPerMin() { return hourPx() / 60; }

/** 分钟数 → 像素 */
function px(minutes) { return minutes * pxPerMin(); }

/**
 * 应用缩放：把轴高写进 CSS 变量，并重排所有依赖几何的元素。
 *
 * 轴高 = 24 小时 × 每小时像素。JS 是唯一计算方，CSS 只消费。
 *
 * 注意 renderTemplate / renderActual 内部各自会清空并重建轴内容
 * （含小时线），所以这里不再单独调 renderHourLines——重复清空虽然
 * 结果正确，但会让"谁负责清轴"这件事变得含糊。
 */
function applyZoom() {
  const axisH = hourPx() * 24;
  document.documentElement.style.setProperty('--axis-h', `${axisH}px`);
  document.documentElement.style.setProperty('--hour-h', `${hourPx()}px`);

  const label = $('zoomLabel');
  if (label) label.textContent = `${+state.zoom.toFixed(3)}×`;

  // 缩放不重新拉数据，只重排已有内容
  renderRuler();
  renderTemplate(state.tplBlocks);
  renderActual(state.rows, state.actualRows);
  document.querySelectorAll('#actAxis .block').forEach(attachBlockEvents);
  renderNowLine();
}

function setZoom(z) {
  state.zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
  applyZoom();
}

function stepZoom(dir) {
  const i = ZOOM_STEPS.findIndex(v => v >= state.zoom - 1e-6);
  const next = dir > 0
    ? ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, (i < 0 ? 0 : i) + 1)]
    : ZOOM_STEPS[Math.max(0, (i < 0 ? ZOOM_STEPS.length : i) - 1)];
  setZoom(next);
}

// ---------- API 层 ----------
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
  compare(date) { return this.req('GET', `/api/compare?date=${date}`); },
  actual(date) { return this.req('GET', `/api/actual?date=${date}`); },
  quick(date, line) { return this.req('POST', '/api/actual/quick', { date, line }); },
  update(id, fields) { return this.req('PUT', `/api/actual/${id}`, fields); },
  remove(id) { return this.req('DELETE', `/api/actual/${id}`); },
  restore(id) { return this.req('POST', `/api/actual/${id}/restore`); },
  templates() { return this.req('GET', '/api/templates'); },
  templateBlocks(id) { return this.req('GET', `/api/templates/${id}/blocks`); },
};

// ---------- 渲染层 ----------
function renderRuler() {
  const ruler = $('ruler');
  ruler.innerHTML = '';
  // 轴太密时逐小时标会糊，按实际像素密度决定标注间隔
  const stepH = hourPx() < 48 ? 3 : hourPx() < 96 ? 2 : 1;
  for (let h = 0; h <= 24; h++) {
    const d = document.createElement('div');
    d.className = 'tick' + (h % stepH === 0 ? '' : ' minor');
    d.style.top = `${px(h * 60)}px`;
    d.textContent = `${String(h).padStart(2, '0')}:00`;
    ruler.appendChild(d);
  }
  const r2 = document.querySelectorAll('.hour-ruler')[1];
  if (r2) r2.innerHTML = ruler.innerHTML;
}

function renderHourLines(axis) {
  axis.innerHTML = '';
  for (let h = 1; h < 24; h++) {
    const l = document.createElement('div');
    const onHour = h % 3 === 0;               // 每 3 小时一条重线，便于定位
    l.className = 'hour-line' + (onHour ? ' major' : '');
    l.style.top = `${px(h * 60)}px`;
    axis.appendChild(l);
  }
  // 半小时的浅虚线，只在足够放大时出现，提供中间参照
  if (hourPx() >= 96) {
    for (let h = 0; h < 24; h++) {
      const l = document.createElement('div');
      l.className = 'half-line';
      l.style.top = `${px(h * 60 + 30)}px`;
      axis.appendChild(l);
    }
  }
}

/** 创建一个块元素。kind: 'template' | 'actual' */
function makeBlock(kind, { name, start, end, status, id, open, badge }) {
  const el = document.createElement('div');
  el.className = `block ${status || ''}${open ? ' open' : ''}`;
  if (id != null) el.dataset.id = id;
  el.dataset.kind = kind;

  const dur = end === null || end === undefined
    ? 30 : Math.max(end - start, 8);
  el.style.top = `${px(start)}px`;
  el.style.height = `${Math.max(px(dur), 12)}px`;
  // 块太矮时文字放不下，交给 CSS 用 data-attr 决定隐藏哪一层
  el.dataset.h = dur >= 22 ? 'tall' : dur >= 12 ? 'mid' : 'short';

  const nm = document.createElement('div');
  nm.className = 'nm';
  nm.textContent = name;
  el.appendChild(nm);

  if (dur >= 22) {
    const tm = document.createElement('div');
    tm.className = 'tm';
    tm.textContent = end === null || end === undefined
      ? `${fmtMin(start)}–进行中` : `${fmtMin(start)}–${fmtMin(end)}`;
    el.appendChild(tm);
  }
  el.title = `${name}｜${fmtMin(start)}–${end === null || end === undefined ? '进行中' : fmtMin(end)}`;
  if (badge) {
    const b = document.createElement('div');
    b.className = 'overlap-badge';
    b.textContent = badge;
    el.appendChild(b);
  }
  return el;
}

function renderTemplate(blocks) {
  const axis = $('tplAxis');
  renderHourLines(axis);
  for (const b of blocks) {
    axis.appendChild(makeBlock('template', {
      name: b.name, start: b.start_min, end: b.end_min, status: 'unrecorded',
    }));
  }
}

/** 渲染实际块（带对照状态）。以 actualRows 为准，保证未闭合块也在。 */
function renderActual(rows, actualRows) {
  const axis = $('actAxis');
  renderHourLines(axis);

  // 建立对照查找：按 (start,end,name) 取最佳状态
  const rank = { unrecorded: 0, offset: 1, aligned: 2, unplanned: 3 };
  const map = new Map();
  for (const r of rows) {
    if (r.actual_start === null || r.actual_end === null) continue;
    const k = `${r.actual_start}|${r.actual_end}|${r.actual_name}`;
    const prev = map.get(k);
    if (!prev || rank[r.status] > rank[prev.status]) map.set(k, r);
  }

  const openRanges = [];
  for (const a of actualRows) {
    const k = `${a.start_min}|${a.end_min}|${a.name}`;
    const r = map.get(k);
    const status = r ? r.status : 'offset';

    // 重叠角标：同轴上与之重叠的块数
    const overlapping = actualRows.filter(o =>
      o.id !== a.id && o.end_min !== null &&
      Math.min(o.end_min, a.end_min === null ? DAY_MIN : a.end_min) >
      Math.max(o.start_min, a.start_min));
    const badge = overlapping.length ? `叠${overlapping.length}` : '';

    const el = makeBlock('actual', {
      name: a.name, start: a.start_min, end: a.end_min,
      status, id: a.id, open: a.end_min === null, badge,
    });
    if (a.end_min === null) openRanges.push(el);
    axis.appendChild(el);
  }
  for (const el of openRanges) attachOpenRangeHint(el);
}

function attachOpenRangeHint(el) {
  el.title = '这块还没填结束时间，点击块名旁的提示补完';
}

// ---------- 交互层 ----------
function selectBlock(el) {
  document.querySelectorAll('.block.selected')
    .forEach(x => x.classList.remove('selected'));
  if (el) { el.classList.add('selected'); state.selectedId = el.dataset.id; }
  else state.selectedId = null;
}

function showToast(text, onUndo) {
  const t = $('toast');
  $('toastText').textContent = text;
  t.hidden = false;
  clearTimeout(state.deleted?.timer);
  state.deleted = {
    timer: setTimeout(() => { t.hidden = true; state.deleted = null; }, REWARD_UNDO_MS),
    onUndo,
  };
  $('toastUndo').onclick = async () => {
    t.hidden = true;
    if (state.deleted?.onUndo) await state.deleted.onUndo();
  };
}

async function deleteBlock(el) {
  const id = el.dataset.id;
  const name = el.querySelector('.nm').textContent;
  const r = await api.remove(id);
  if (!r.ok) { flashError(`删除失败：${r.data?.detail || r.status}`); return; }
  el.remove();
  showToast(`已删除「${name}」`, async () => {
    await api.restore(id);
    await load();
  });
}

async function renameBlock(el) {
  const id = el.dataset.id;
  const nmEl = el.querySelector('.nm');
  const old = nmEl.textContent;

  const input = document.createElement('input');
  input.className = 'rename-input';
  input.value = old;
  nmEl.replaceWith(input);
  input.focus();
  input.select();

  const commit = async () => {
    const v = input.value.trim();
    if (!v || v === old) { await load(); return; }
    const r = await api.update(id, { name: v });
    if (!r.ok) flashError(`改名失败：${r.data?.detail || r.status}`);
    await load();
  };
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.value = old; input.blur(); }
  });
  input.addEventListener('blur', commit, { once: true });
}

/** 微调：±5 分钟（Shift 为 ±15） */
async function nudge(el, minutes) {
  const id = el.dataset.id;
  const a = state.actualRows.find(x => String(x.id) === String(id));
  if (!a) return;
  const fields = { start_min: Math.max(0, a.start_min + minutes) };
  if (a.end_min !== null) fields.end_min = a.end_min + minutes;
  const r = await api.update(id, fields);
  if (!r.ok) { flashError(`调整失败：${r.data?.detail || r.status}`); return; }
  await load();
}

/** 拖动：整块移动或拉伸边缘 */
function onPointerDown(e, el, mode) {
  const a = state.actualRows.find(x => String(x.id) === String(el.dataset.id));
  if (!a) return;
  e.preventDefault();
  selectBlock(el);
  state.drag = {
    el, id: a.id, mode,
    y0: e.clientY,
    start0: a.start_min,
    end0: a.end_min === null ? a.start_min + 30 : a.end_min,
    moved: false,
  };
  el.setPointerCapture?.(e.pointerId);
}

async function onPointerMove(e) {
  const d = state.drag;
  if (!d) return;
  const delta = Math.round((e.clientY - d.y0) / pxPerMin());
  if (Math.abs(delta) < 2) return;
  d.moved = true;
  const s = snap(delta);

  let newStart = d.start0, newEnd = d.end0;
  if (d.mode === 'move') { newStart = Math.max(0, d.start0 + s); newEnd = newStart + (d.end0 - d.start0); }
  else if (d.mode === 'top') { newStart = Math.max(0, Math.min(d.start0 + s, d.end0 - 5)); }
  else if (d.mode === 'bottom') { newEnd = Math.max(d.start0 + 5, d.end0 + s); }

  // 实时预览
  d.el.style.top = `${px(newStart)}px`;
  d.el.style.height = `${Math.max(px(newEnd - newStart), 12)}px`;
  // 拖到边缘时自动滚动容器，否则长轴下没法把块拖到视野外的时间
  autoScrollDuringDrag(e.clientY);
  d.pending = { newStart, newEnd };
}

/** 拖动到滚动区上/下边缘附近时自动滚动 */
function autoScrollDuringDrag(clientY) {
  const box = document.querySelector('.scroll-area');
  if (!box) return;
  const r = box.getBoundingClientRect();
  const EDGE = 48, SPEED = 12;
  if (clientY < r.top + EDGE) box.scrollTop -= SPEED;
  else if (clientY > r.bottom - EDGE) box.scrollTop += SPEED;
}

async function onPointerUp(e) {
  const d = state.drag;
  if (!d) return;
  state.drag = null;

  if (!d.moved || !d.pending) return;
  const { newStart, newEnd } = d.pending;
  const r = await api.update(d.id, { start_min: newStart, end_min: newEnd });
  if (!r.ok) flashError(`保存失败：${r.data?.detail || r.status}`);
  await load();
}

function attachBlockEvents(el) {
  const kind = el.dataset.kind;

  // 删除按钮（仅实际块）
  if (kind === 'actual') {
    const del = document.createElement('div');
    del.className = 'del';
    del.textContent = '×';
    del.title = '删除（5 秒内可撤销）';
    del.addEventListener('click', e => { e.stopPropagation(); deleteBlock(el); });
    el.appendChild(del);

    // 边缘把手
    for (const m of ['top', 'bottom']) {
      const h = document.createElement('div');
      h.className = `edge ${m}`;
      h.addEventListener('pointerdown', e => { e.stopPropagation(); onPointerDown(e, el, m); });
      el.appendChild(h);
    }

    // 双击改名
    el.addEventListener('dblclick', e => { e.stopPropagation(); renameBlock(el); });
    // 单击选中
    el.addEventListener('click', () => selectBlock(el));
    // 拖动整块
    el.addEventListener('pointerdown', e => {
      if (e.target.classList.contains('edge') || e.target.classList.contains('del')) return;
      onPointerDown(e, el, 'move');
    });
  }
}

// ---------- 快速记录 ----------
function flashError(msg) {
  const box = $('quickError');
  box.innerHTML = msg;
  box.hidden = false;
  clearTimeout(flashError._t);
  flashError._t = setTimeout(() => { box.hidden = true; }, 6000);
}

async function submitQuick() {
  const input = $('quickInput');
  const line = input.value.trim();
  if (!line) return;

  const r = await api.quick(state.date, line);
  if (r.status === 422) {
    // 保留输入内容——丢一次输入用户就再也不信任它了
    flashError(`没能看懂这一行，请检查：<code>${escapeHtml(r.data.raw || line)}</code>`);
    input.focus();
    return;
  }
  if (!r.ok) { flashError(`记录失败：${r.data?.detail || r.status}`); return; }

  input.value = '';
  $('quickError').hidden = true;
  await load();
  input.focus();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---------- 当前时刻线 ----------
/** 只在查看「今天」时显示。昨天/明天的轴画一条"现在"线没有意义。 */
function renderNowLine() {
  document.querySelectorAll('.now-line').forEach(e => e.remove());
  if (state.date !== todayISO()) return;

  const now = new Date();
  const m = now.getHours() * 60 + now.getMinutes();
  for (const ax of [$('tplAxis'), $('actAxis')]) {
    if (!ax) continue;
    const l = document.createElement('div');
    l.className = 'now-line';
    l.style.top = `${px(m)}px`;
    l.innerHTML = `<span>${fmtMin(m)}</span>`;
    ax.appendChild(l);
  }
}

// ---------- 滚动联动 ----------
/** 两栏必须同屏对照，所以任一栏滚动都要带动另一栏。 */
function bindScrollSync() {
  const areas = Array.from(document.querySelectorAll('.scroll-area'));
  if (areas.length < 2) return;
  let syncing = false;
  for (const a of areas) {
    a.addEventListener('scroll', () => {
      if (syncing) return;
      syncing = true;
      for (const b of areas) {
        if (b !== a && b.scrollTop !== a.scrollTop) b.scrollTop = a.scrollTop;
      }
      // 松开标志放到下一帧，避免互相触发的抖动
      requestAnimationFrame(() => { syncing = false; });
    }, { passive: true });
  }
}

/** 滚轮缩放：Ctrl/⌘+滚轮，普通滚轮留给滚动本身 */
function bindWheelZoom() {
  const box = document.querySelector('.columns');
  if (!box) return;
  box.addEventListener('wheel', e => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();

    const area = e.target.closest('.scroll-area');

    // 记录锚点：鼠标指向的那个时间点，缩放后尽量停在原地
    let anchor = null;
    if (area) {
      const r = area.getBoundingClientRect();
      const offsetInBox = e.clientY - r.top;          // 鼠标在可视区内的高度
      const totalH = area.querySelector('.axis-wrap').getBoundingClientRect().height
                     || hourPx() * 24;
      const ratio = (area.scrollTop + offsetInBox) / totalH;
      anchor = { offsetInBox, ratio };
    }

    stepZoom(e.deltaY < 0 ? 1 : -1);

    if (anchor) {
      const totalH = hourPx() * 24;
      const top = Math.max(0, anchor.ratio * totalH - anchor.offsetInBox);
      for (const a of document.querySelectorAll('.scroll-area')) a.scrollTop = top;
    }
  }, { passive: false });
}

// ---------- 加载 ----------
async function load() {
  $('actualDate').textContent = state.date;
  const [cmp, act, tpls] = await Promise.all([
    api.compare(state.date), api.actual(state.date), api.templates(),
  ]);

  if (tpls.ok && tpls.data.length) {
    const t = tpls.data.find(x => x.is_default) || tpls.data[0];
    state.templateName = t.name;
    $('tplName').textContent = t.name;
    const tb = await api.templateBlocks(t.id);
    if (tb.ok) { state.tplBlocks = tb.data; renderTemplate(tb.data); }
  }

  if (cmp.ok) state.rows = cmp.data.rows;
  if (act.ok) state.actualRows = act.data;

  renderActual(state.rows, state.actualRows);
  renderNowLine();

  document.querySelectorAll('#actAxis .block').forEach(attachBlockEvents);
  // 数据回来后把当前时刻滚进视野，省掉手动找
  scrollToNowIfToday();
}

/** 首次加载时把视图滚到当前时刻附近（仅今天） */
let didInitialScroll = false;
function scrollToNowIfToday() {
  if (didInitialScroll || state.date !== todayISO()) return;
  const area = document.querySelector('.scroll-area');
  if (!area) return;
  const now = new Date();
  const m = now.getHours() * 60 + now.getMinutes();
  area.scrollTop = Math.max(0, px(m) - area.clientHeight / 2);
  didInitialScroll = true;
}

async function exportFile(fmt) {
  const url = `/api/export?start=${state.date}&end=${state.date}&format=${fmt}`;
  const r = await fetch(url);
  if (!r.ok) { flashError(`导出失败：${r.status}`); return; }
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `timeline_${state.date}.${fmt}`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function shiftDay(n) {
  const d = new Date(state.date + 'T00:00:00');
  d.setDate(d.getDate() + n);
  const p = x => String(x).padStart(2, '0');
  state.date = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  $('datePicker').value = state.date;
  load();
}

// ---------- 启动 ----------
function boot() {
  applyZoom();                       // 先定轴高，后续渲染才有正确的几何基准
  $('datePicker').value = state.date;

  $('prevDay').onclick = () => shiftDay(-1);
  $('nextDay').onclick = () => shiftDay(1);
  $('today').onclick = () => { state.date = todayISO(); $('datePicker').value = state.date; load(); };
  $('datePicker').onchange = e => { state.date = e.target.value; load(); };
  $('quickSubmit').onclick = submitQuick;
  $('quickInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); submitQuick(); }
  });
  $('exportCsv').onclick = () => exportFile('csv');
  $('exportXlsx').onclick = () => exportFile('xlsx');

  // 缩放控件
  $('zoomIn').onclick = () => stepZoom(1);
  $('zoomOut').onclick = () => stepZoom(-1);
  $('zoomReset').onclick = () => setZoom(ZOOM_DEFAULT);

  bindScrollSync();
  bindWheelZoom();

  document.addEventListener('pointermove', onPointerMove);
  document.addEventListener('pointerup', onPointerUp);
  document.addEventListener('keydown', e => {
    // 缩放快捷键（不干扰方向键微调）
    if ((e.ctrlKey || e.metaKey) && (e.key === '=' || e.key === '+')) {
      e.preventDefault(); stepZoom(1); return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === '-') {
      e.preventDefault(); stepZoom(-1); return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === '0') {
      e.preventDefault(); setZoom(ZOOM_DEFAULT); return;
    }
    // 跳到当前时刻
    if (e.key === 'n' && document.activeElement.tagName !== 'INPUT') {
      scrollToNow(true); return;
    }

    const el = document.querySelector('.block.selected');
    if (!el) return;
    if (e.key === 'Delete' || e.key === 'Backspace') {
      if (document.activeElement.tagName === 'INPUT') return;
      e.preventDefault(); deleteBlock(el);
    }
    if (e.key === 'ArrowUp') { e.preventDefault(); nudge(el, e.shiftKey ? -15 : -5); }
    if (e.key === 'ArrowDown') { e.preventDefault(); nudge(el, e.shiftKey ? 15 : 5); }
  });

  // 每分钟刷新一次"现在"线
  setInterval(renderNowLine, 60000);

  load();
}

/** 滚动到当前时刻。force=true 时忽略"仅今天"的限制。 */
function scrollToNow(force) {
  const area = document.querySelector('.scroll-area');
  if (!area) return;
  if (!force && state.date !== todayISO()) return;
  const now = new Date();
  const m = now.getHours() * 60 + now.getMinutes();
  area.scrollTop = Math.max(0, px(m) - area.clientHeight / 2);
}

document.addEventListener('DOMContentLoaded', boot);
