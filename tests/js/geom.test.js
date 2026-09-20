const BASE_HOUR_PX = 72;
const state = { zoom: 1 };
const hourPx = () => BASE_HOUR_PX * state.zoom;
const pxPerMin = () => hourPx() / 60;
const px = m => m * pxPerMin();

const cases = [];
function check(name, got, want, tol) {
  tol = (tol === undefined) ? 0.51 : tol;
  const ok = Math.abs(got - want) <= tol;
  cases.push({ name: name, got: +got.toFixed(2), want: want, ok: ok });
}

state.zoom = 1;
check('轴高 24h @1x', hourPx() * 24, 1728);
check('午饭 720min 的 top', px(720), 864);
check('午饭 30min 的高度', px(30), 36);
check('跨零点 1360->1830 高度', px(1830 - 1360), 564);

state.zoom = 2;
check('轴高 24h @2x', hourPx() * 24, 3456);
check('top @2x 翻倍', px(720), 1728);

state.zoom = 0.5;
check('轴高 24h @0.5x', hourPx() * 24, 864);
check('top @0.5x 减半', px(720), 432);

state.zoom = 1;   const r1 = px(720) / (hourPx() * 24);
state.zoom = 3;   const r3 = px(720) / (hourPx() * 24);
check('相对位置不随缩放改变', r1, r3, 0.0001);

state.zoom = 1;
check('5 分钟块高 @1x', px(5), 6);
check('5 分钟块被下限提到 12px', Math.max(px(5), 12), 12);

let fail = 0;
for (const c of cases) {
  if (!c.ok) fail++;
  const pad = c.name.padEnd(26);
  console.log((c.ok ? 'PASS' : 'FAIL') + '  ' + pad + ' got=' + c.got + '  want=' + c.want);
}
console.log('---');
console.log((cases.length - fail) + '/' + cases.length + ' 通过');
process.exit(fail ? 1 : 0);
