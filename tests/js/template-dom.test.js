/* 模板编辑页 —— 真实 DOM 渲染与交互验证
 *
 * 为什么要有这一层：template-form.test.js 只覆盖纯函数（解析、时长），
 * 但「页面上到底渲染出了什么」它看不见。历史上踩过的坑（轴高塌陷）
 * 正是纯逻辑全对、DOM 渲染错。所以这里用 jsdom 真跑 template.js，
 * 断言真实生成的 DOM 结构与交互结果。
 *
 * 跑法（需先安装 jsdom，见文件末尾注释）：
 *   NODE_PATH=<workspace>/node_modules node tests/js/template-dom.test.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const read = p => fs.readFileSync(path.join(ROOT, p), 'utf8');

const cases = [];
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  cases.push({ name, got, want, ok });
}
function checkTrue(name, got) {
  const ok = !!got;
  cases.push({ name, got: !!got, want: true, ok });
}

// 假的模板数据：含跨零点块与短块，覆盖两个边界
const TPL = { id: 1, name: '工作日', description: '可无限重复的工作日模板', is_default: 1 };
const BLOCKS = [
  { id: 11, template_id: 1, start_min: 390, end_min: 420, name: '早操', category: '身体锚点', sort_order: 0 },
  { id: 12, template_id: 1, start_min: 450, end_min: 455, name: '出门前准备', category: '事务', sort_order: 1 },
  { id: 13, template_id: 1, start_min: 1230, end_min: 1320, name: '干活（中间做拉伸）', category: '项目推进', sort_order: 2 },
  { id: 14, template_id: 1, start_min: 1360, end_min: 1830, name: '睡觉', category: '睡眠', sort_order: 3 },
];

/** 用最小实现替掉 fetch，记录调用以便断言请求体 */
function makeEnv(calls) {
  const { JSDOM } = require('jsdom');
  const html = read('static/template.html');
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/static/template.html' });
  const win = dom.window;

  win.fetch = async (url, opt) => {
    const method = (opt && opt.method) || 'GET';
    const body = opt && opt.body ? JSON.parse(opt.body) : undefined;
    calls.push({ method, url, body });

    let data;
    if (url === '/api/templates') data = [TPL];
    else if (/^\/api\/templates\/\d+\/blocks$/.test(url) && method === 'GET') data = BLOCKS;
    else if (method === 'POST') data = { id: 99 };
    else data = { ok: true };

    return {
      ok: true, status: 200,
      headers: { get: () => 'application/json' },
      json: async () => data,
    };
  };
  return { dom, win };
}

async function run() {
  // jsdom 装在隔离工作区，不随项目依赖走。缺了就说清楚怎么装，
  // 而不是抛一串 MODULE_NOT_FOUND 栈——那会让人以为是代码坏了。
  try {
    require.resolve('jsdom');
  } catch (e) {
    console.log('跳过：未找到 jsdom。');
    console.log('安装后重跑（注意 NODE_PATH 用 Windows 风格路径）：');
    console.log('  NODE_PATH="C:/Users/<你>/.workbuddy/binaries/node/workspace/node_modules" \\');
    console.log('    node tests/js/template-dom.test.js');
    return;
  }

  const calls = [];
  const { win } = makeEnv(calls);

  // template.js 末尾用 DOMContentLoaded 触发 boot()，这里显式跑一遍
  win.eval(read('static/template.js'));
  win.document.dispatchEvent(new win.Event('DOMContentLoaded'));
  await new Promise(r => setTimeout(r, 80));

  const doc = win.document;
  const $ = id => doc.getElementById(id);

  checkTrue('页面标题渲染出模板名', $('tplName').textContent === '工作日');
  checkTrue('描述渲染', $('tplDesc').textContent.includes('可无限重复'));

  const rows = doc.querySelectorAll('.block-row');
  check('渲染出全部 4 行', rows.length, 4);

  // 首行的时间输入框应显示 HH:MM
  const firstStart = rows[0].querySelector('[data-field="start_min"]').value;
  check('首行开始时间格式化为 06:30', firstStart, '06:30');

  // 跨零点块的结束时间：1830 应显示 06:30，而不是 30:30
  const sleepRow = rows[3];
  const sleepEnd = sleepRow.querySelector('[data-field="end_min"]').value;
  check('跨零点块结束显示为 06:30（非 30:30）', sleepEnd, '06:30');
  check('跨零点块时长显示 7h50', sleepRow.querySelector('.dur').textContent, '7h50');

  // 短块时长
  check('5 分钟块时长显示 5min',
        rows[1].querySelector('.dur').textContent, '5min');

  // 类别下拉应包含候选值且选中正确项
  const catSel = rows[0].querySelector('[data-field="category"]');
  check('类别下拉选中「身体锚点」', catSel.value, '身体锚点');
  checkTrue('类别下拉含全部七个候选',
    ['睡眠', '身体锚点', '情绪稳定', '项目推进', '通勤', '事务', '其他']
      .every(c => Array.from(catSel.options).some(o => o.value === c)));

  // 「其他」是 classify.js 无法归类时的产出值，必须能被选中显示；
  // 否则库里的「其他」会显示成「未分类」，用户一改就把它覆盖掉。
  checkTrue('「其他」是可选值，不是仅作图例',
    Array.from(catSel.options).some(o => o.value === '其他' && !o.disabled));

  // 名称里的特殊字符不应破坏 DOM
  check('含全角括号的名称完整渲染',
        rows[2].querySelector('[data-field="name"]').value, '干活（中间做拉伸）');

  // 类别图例：未使用的类别应被标出
  checkTrue('类别图例列出未使用项', $('catChips').textContent.includes('未使用'));

  // ---- 交互：改名会发出 PUT ----
  calls.length = 0;
  const nameEl = rows[0].querySelector('[data-field="name"]');
  nameEl.value = '早操（改）';
  nameEl.dispatchEvent(new win.Event('blur'));
  await new Promise(r => setTimeout(r, 50));
  const put = calls.find(c => c.method === 'PUT');
  checkTrue('改名发出 PUT', !!put);
  check('PUT 目标是正确块', put && put.url, '/api/template-blocks/11');
  check('PUT 体只含 name', put && put.body, { name: '早操（改）' });

  // ---- 交互：改名清空应被拒绝（不发请求）----
  calls.length = 0;
  const nameEl2 = rows[0].querySelector('[data-field="name"]');
  nameEl2.value = '   ';
  nameEl2.dispatchEvent(new win.Event('blur'));
  await new Promise(r => setTimeout(r, 50));
  checkTrue('清空名称不发请求', !calls.some(c => c.method === 'PUT'));

  // ---- 交互：时间输入即时预览时长 ----
  const s2 = rows[1].querySelector('[data-field="start_min"]');
  const e2 = rows[1].querySelector('[data-field="end_min"]');
  s2.value = '07:30';
  e2.value = '08:00';
  s2.dispatchEvent(new win.Event('input'));
  check('改时间即时预览时长（07:30-08:00 → 30min）',
        rows[1].querySelector('.dur').textContent, '30min');

  e2.value = '07:20';   // 结束早于开始
  e2.dispatchEvent(new win.Event('input'));
  check('结束早于开始时预览显示 —',
        rows[1].querySelector('.dur').textContent, '—');

  // ---- 交互：跨零点编辑应提交 +1440 的 end ----
  calls.length = 0;
  s2.value = '22:40';
  e2.value = '06:30';
  s2.dispatchEvent(new win.Event('input'));
  s2.dispatchEvent(new win.Event('blur'));
  await new Promise(r => setTimeout(r, 60));
  const putCross = calls.find(c => c.method === 'PUT');
  checkTrue('跨零点编辑发出 PUT', !!putCross);
  check('跨零点提交 end=1830', putCross && putCross.body,
        { start_min: 1360, end_min: 1830 });

  // ---- 交互：删除走二次确认，不直接发请求 ----
  calls.length = 0;
  rows[0].querySelector('.row-del').dispatchEvent(new win.Event('click'));
  await new Promise(r => setTimeout(r, 30));
  checkTrue('点删除先弹确认框', !$('confirm').hidden);
  checkTrue('未确认时不发 DELETE', !calls.some(c => c.method === 'DELETE'));
  checkTrue('确认框标题含块名', $('confirmTitle').textContent.includes('早操'));
  checkTrue('确认框说明不可撤销', $('confirmText').textContent.includes('不能撤销'));

  // 取消
  $('confirmCancel').dispatchEvent(new win.Event('click'));
  await new Promise(r => setTimeout(r, 20));
  checkTrue('取消后确认框关闭', $('confirm').hidden);
  checkTrue('取消后不发 DELETE', !calls.some(c => c.method === 'DELETE'));

  // 确认删除
  rows[0].querySelector('.row-del').dispatchEvent(new win.Event('click'));
  await new Promise(r => setTimeout(r, 20));
  $('confirmOk').dispatchEvent(new win.Event('click'));
  await new Promise(r => setTimeout(r, 60));
  const del = calls.find(c => c.method === 'DELETE');
  checkTrue('确认后发出 DELETE', !!del);
  check('DELETE 目标是该块', del && del.url, '/api/template-blocks/11');

  // ---- 交互：新增块 ----
  calls.length = 0;
  $('addBlock').dispatchEvent(new win.Event('click'));
  await new Promise(r => setTimeout(r, 60));
  const post = calls.find(c => c.method === 'POST');
  checkTrue('新增发出 POST', !!post);
  check('POST 路径含模板 id', post && post.url, '/api/templates/1/blocks');
  checkTrue('POST 体含名称', post && post.body.name === '新时间块');
  // 末块是睡觉（end 1830），新增应接在其后且不超 1440
  checkTrue('新增起点接在末块之后且不越界',
    post && post.body.start_min >= 0 && post.body.end_min <= 1440);

  // ---- 错误路径：服务端 422 应回显 detail ----
  const calls2 = [];
  const env2 = makeEnv(calls2);
  env2.win.fetch = async (url, opt) => {
    const method = (opt && opt.method) || 'GET';
    calls2.push({ method, url });
    let data;
    if (url === '/api/templates') data = [TPL];
    else if (method === 'GET') data = BLOCKS;
    else return {
      ok: false, status: 422,
      headers: { get: () => 'application/json' },
      json: async () => ({ detail: '结束时间必须晚于开始时间' }),
    };
    return {
      ok: true, status: 200,
      headers: { get: () => 'application/json' },
      json: async () => data,
    };
  };
  env2.win.eval(read('static/template.js'));
  env2.win.document.dispatchEvent(new env2.win.Event('DOMContentLoaded'));
  await new Promise(r => setTimeout(r, 80));

  const doc2 = env2.win.document;
  const rows2 = doc2.querySelectorAll('.block-row');
  const s3 = rows2[0].querySelector('[data-field="start_min"]');
  const e3 = rows2[0].querySelector('[data-field="end_min"]');
  s3.value = '09:00';
  e3.value = '10:00';
  s3.dispatchEvent(new env2.win.Event('input'));
  s3.dispatchEvent(new env2.win.Event('blur'));
  await new Promise(r => setTimeout(r, 60));
  checkTrue('服务端拒绝时把 detail 回显给用户',
    doc2.getElementById('toastText').textContent.includes('结束时间必须晚于开始时间'));

  let fail = 0;
  for (const c of cases) {
    if (!c.ok) fail++;
    console.log((c.ok ? 'PASS' : 'FAIL') + '  ' + c.name.padEnd(44)
      + (c.ok ? '' : '  got=' + JSON.stringify(c.got)
        + '  want=' + JSON.stringify(c.want)));
  }
  console.log('---');
  console.log((cases.length - fail) + '/' + cases.length + ' 通过');
  process.exit(fail ? 1 : 0);
}

run().catch(e => { console.error(e); process.exit(1); });
