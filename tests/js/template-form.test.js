/* 模板编辑页的时间解析与时长计算 —— 纯逻辑断言
 *
 * 这些函数是从 static/template.js 复制过来的，与 geom.test.js 同一套路：
 * 不依赖浏览器，直接跑 Node。之所以要单独钉住，是因为编辑页的时间解析
 * 与快速记录框的解析器（app/parser.py）是**两套独立实现**——它们是
 * 不同语言、不同入口，任何一边改都可能让两边手感不一致。
 *
 * 已经踩过一回单位混淆的坑（state.zoom 倍率/像素混用），
 * 所以凡是有换算的地方都要有断言。
 */
const DAY_MIN = 1440;

function fmtMin(m) {
  if (m === null || m === undefined) return '';
  const h = Math.floor(m / 60) % 24, mi = m % 60;
  return `${String(h).padStart(2, '0')}:${String(mi).padStart(2, '0')}`;
}

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

const cases = [];
function check(name, got, want) {
  cases.push({ name: name, got: got, want: want, ok: got === want });
}

// ---- parseTime：与 parser.py 支持同样的写法 ----
check('标准 HH:MM', parseTime('08:30'), 510);
check('单数字小时', parseTime('8:05'), 485);
check('点号分隔', parseTime('20.30'), 1230);
check('紧凑四位', parseTime('2030'), 1230);
check('紧凑三位', parseTime('830'), 510);
check('全角数字与冒号', parseTime('２０：３０'), 1230);
check('全角点号', parseTime('20。30'), 1230);
check('前后空白', parseTime('  09:00  '), 540);
check('零点', parseTime('00:00'), 0);
check('24:00 合法', parseTime('24:00'), 1440);

check('空串返回 null', parseTime(''), null);
check('纯文字返回 null', parseTime('早上'), null);
check('缺分钟返回 null', parseTime('8:'), null);
check('分钟超 59 返回 null', parseTime('08:75'), null);
check('小时超 24 返回 null', parseTime('25:00'), null);
check('负数返回 null', parseTime('-1:00'), null);

// 已知歧义，不改：'8.5' 被解读为 8 时 5 分（而非 8 时 30 分）。
// 理由是与 '20.30' 的解读必须一致——点号在本解析器里是「时分分隔符」
// 而非小数点。若把 '8.5' 特判成半小时，就会出现 '8.5'=8:30 但 '20.30'=20:30
// 的分叉，那种不一致比现在这个歧义更难排查。app/parser.py 行为相同，
// 两端保持一致。真正想表达 8 时 30 分请写 '8:30' 或 '830'。
check("'8.5' 解读为 8:05（与 parser.py 一致）", parseTime('8.5'), 485);
check("'20.30' 解读为 20:30", parseTime('20.30'), 1230);

// ---- fmtMin / fmtMinCross：跨零点必须标出「次日」 ----
check('510 → 08:30', fmtMin(510), '08:30');
check('1360 → 22:40', fmtMin(1360), '22:40');
check('1830 显示为 06:30（不进位到 30）', fmtMin(1830), '06:30');
check('1830 跨零点时标注次日', fmtMinCross(1830), '次日 06:30');
check('1440 不标次日', fmtMinCross(1440), '00:00');
check('1441 标次日', fmtMinCross(1441), '次日 00:01');

// ---- durationLabel ----
check('470 分钟 → 7h50', durationLabel(1360, 1830), '7h50');
check('整点 → 2h', durationLabel(600, 720), '2h');
check('不足 1 小时 → 45min', durationLabel(720, 765), '45min');
check('5 分钟块 → 5min', durationLabel(450, 455), '5min');
check('反向区间返回 —（不该算出负数时长）', durationLabel(600, 300), '—');
check('零长区间返回 —', durationLabel(600, 600), '—');

// ---- 跨零点编辑：结束小于开始时按次日算 ----
function normalizeEnd(s, e) { return e <= s ? e + DAY_MIN : e; }
check('22:40 → 06:30 跨零点', normalizeEnd(1360, 390), 1830);
check('08:30 → 12:00 同日内不变', normalizeEnd(510, 720), 720);
check('跨零点时长 7h50', normalizeEnd(1360, 390) - 1360, 470);

let fail = 0;
for (const c of cases) {
  if (!c.ok) fail++;
  console.log((c.ok ? 'PASS' : 'FAIL') + '  ' + c.name.padEnd(34)
    + ' got=' + JSON.stringify(c.got) + '  want=' + JSON.stringify(c.want));
}
console.log('---');
console.log((cases.length - fail) + '/' + cases.length + ' 通过');
process.exit(fail ? 1 : 0);
