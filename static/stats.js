/* 统计页 —— 区间聚合与漏做清单
 *
 * 数据来源单一：/api/stats（后端已复用 compare_day，不重算）。
 * 本文件只做展示，不含任何业务判定逻辑——判定口径若改动，
 * 只需改后端一处。
 */
'use strict';

const $ = id => document.getElementById(id);

function todayISO() {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function shiftISO(iso, days) {
  const d = new Date(iso + 'T00:00:00');
  d.setDate(d.getDate() + days);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function fmtMin(m) {
  if (m === null || m === undefined || m === '') return '—';
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`;
}

async function fetchJSON(url) {
  const r = await fetch(url);
  if (r.status === 401) { location.href = '/static/login.html'; throw new Error('未授权'); }
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

// daily 行是按位置排列的数组，后端 stats.py 定义其顺序
const D_DATE = 0, D_RECORDED = 1, D_UNPLANNED_MIN = 2,
      D_ALIGNED = 3, D_OFFSET = 4, D_UNRECORDED = 5, D_UNPLANNED = 6;

/** metric 列表 → 便于按名取值 */
function metricMap(pairs) {
  const m = new Map();
  for (const [k, v] of pairs) m.set(k, v);
  return m;
}

function card(k, v, s) {
  return `<div class="stat-card"><div class="k">${k}</div>
          <div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ''}</div>`;
}

function renderRange(pairs) {
  const m = metricMap(pairs);
  const days = m.get('days') || 0;
  const pct = x => `${Math.round((x || 0) * 100)}%`;

  $('rangeCards').innerHTML = [
    card('统计天数', days, `${m.get('days') || 0} 天`),
    card('睡眠达标', pct(m.get('sleep_hit_rate')),
         `${m.get('sleep_hit_days') || 0} 天 · 门槛 7 小时`),
    card('运动达标', pct(m.get('exercise_hit_rate')),
         `${m.get('exercise_hit_days') || 0} 天 · 早晚操 5–20 分钟`),
    card('低刺激时间', pct(m.get('low_stimulus_rate')),
         `${m.get('low_stimulus_days') || 0} 天有记录`),
    card('项目推进合计', fmtMin(m.get('project_min_total')),
         `日均 ${m.get('project_min_avg') || 0} 分钟`),
    card('落在 45–90 分钟', `${m.get('project_in_range_days') || 0} 天`,
         '理想区间'),
    card('计划外合计', fmtMin(m.get('unplanned_min_total')), '越少越好'),
  ].join('');
}

function renderDaily(daily) {
  if (!daily.length) { $('dailyTable').innerHTML = '<div class="empty">这段时间没有数据</div>'; return; }
  const rows = daily.map(r => {
    const recorded = r[D_RECORDED];
    const total = r[D_ALIGNED] + r[D_OFFSET] + r[D_UNRECORDED];
    const hit = total ? Math.round(r[D_ALIGNED] / total * 100) : 0;
    return `<tr>
      <td>${r[D_DATE]}</td>
      <td>${fmtMin(recorded)}</td>
      <td><span class="pill aligned">${r[D_ALIGNED]}</span></td>
      <td><span class="pill offset">${r[D_OFFSET]}</span></td>
      <td><span class="pill unrecorded">${r[D_UNRECORDED]}</span></td>
      <td><span class="pill unplanned">${r[D_UNPLANNED]}</span></td>
      <td>${fmtMin(r[D_UNPLANNED_MIN])}</td>
      <td>${hit}%</td>
    </tr>`;
  }).join('');
  $('dailyTable').innerHTML = `<table class="data">
    <thead><tr><th>日期</th><th>已记录</th><th>对齐</th><th>偏移</th>
    <th>未记录</th><th>计划外</th><th>计划外时长</th><th>对齐率</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

/** 漏做清单：哪些模板块最常 unrecorded / offset */
function renderGaps(daily) {
  // daily 行里不含模板块名，需要额外拉一天一份的对照结果代价太高。
  // 改为在区间内累计：以「未记录数」为主的粗粒度提示。
  let unrecorded = 0, offset = 0, unplanned = 0, aligned = 0;
  for (const r of daily) {
    aligned += r[D_ALIGNED]; offset += r[D_OFFSET];
    unrecorded += r[D_UNRECORDED]; unplanned += r[D_UNPLANNED];
  }
  const total = aligned + offset + unrecorded + unplanned;
  if (!total) { $('gapTable').innerHTML = '<div class="empty">暂无数据</div>'; return; }

  const share = n => `${(n / total * 100).toFixed(0)}%`;
  const items = [
    ['未记录', unrecorded, '模板里有、但完全没记的块'],
    ['偏移', offset, '做了但时间和模板对不齐'],
    ['计划外', unplanned, '模板里没有、实际发生了'],
    ['对齐', aligned, '时间和内容都吻合'],
  ].sort((a, b) => b[1] - a[1]);

  $('gapTable').innerHTML = `<table class="data">
    <thead><tr><th>状态</th><th>出现次数</th><th>占比</th><th>说明</th></tr></thead>
    <tbody>${items.map(([k, n, d]) =>
      `<tr><td><span class="pill ${k === '未记录' ? 'unrecorded'
        : k === '偏移' ? 'offset'
        : k === '计划外' ? 'unplanned' : 'aligned'}">${k}</span></td>
       <td>${n}</td><td>${share(n)}</td><td>${d}</td></tr>`).join('')}
    </tbody></table>`;
}

async function load() {
  const start = $('start').value, end = $('end').value;
  if (!start || !end) return;
  if (end < start) { $('rangeCards').innerHTML = '<div class="empty">结束日期不能早于开始日期</div>'; return; }
  $('rangeCards').innerHTML = '<div class="loading">加载中…</div>';
  try {
    const d = await fetchJSON(`/api/stats?start=${start}&end=${end}`);
    renderRange(d.range);
    renderDaily(d.daily);
    renderGaps(d.daily);
  } catch (e) {
    $('rangeCards').innerHTML = `<div class="empty">加载失败：${e.message}</div>`;
    $('dailyTable').innerHTML = '';
    $('gapTable').innerHTML = '';
  }
}

async function exportFile(fmt) {
  const start = $('start').value, end = $('end').value;
  const url = `/api/export?start=${start}&end=${end}&format=${fmt}`;
  const r = await fetch(url);
  if (!r.ok) { alert(`导出失败：${r.status}`); return; }
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `timeline_${start}_${end}.${fmt}`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function boot() {
  const today = todayISO();
  $('start').value = shiftISO(today, -6);
  $('end').value = today;

  document.querySelectorAll('.stats-controls button[data-range]').forEach(b => {
    b.onclick = () => {
      const n = Number(b.dataset.range);
      $('end').value = todayISO();
      $('start').value = shiftISO(todayISO(), -(n - 1));
      load();
    };
  });
  $('apply').onclick = load;
  $('start').onchange = load;
  $('end').onchange = load;
  $('exportCsv').onclick = () => exportFile('csv');
  $('exportXlsx').onclick = () => exportFile('xlsx');

  load();
}

document.addEventListener('DOMContentLoaded', boot);
