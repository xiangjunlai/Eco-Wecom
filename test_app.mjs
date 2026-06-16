import { chromium } from 'playwright';

const BASE = 'http://localhost:9090';
const API = 'http://localhost:8000';

// Valid invitation codes (must match provider_name)
const VALID_CODES = [
  { code: 'PROV2026001', provider: '测试服务商A' },
  { code: 'PROV2026002', provider: '测试服务商B' },
  { code: 'PROV2026003', provider: '上海数字科技' },
  { code: 'PROV2026004', provider: '深圳智能服务' },
  { code: 'PROV2026005', provider: '北京企业服务' },
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', err => errors.push(err.message));
  page.on('response', async r => {
    if (r.url().includes('localhost:8000')) {
      console.log('  API:', r.url().replace(API,''), r.status());
    }
  });

  // === Setup: create user via API ===
  console.log('=== Setup: Create user via API ===');
  const ts = Date.now();
  const cred = VALID_CODES[ts % VALID_CODES.length];
  const regData = {
    provider_name: cred.provider,
    invitation_code: cred.code,
    username: 'user' + ts,
    password: 'Test1234!'
  };

  // Register
  const regR = await fetch(`${API}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(regData)
  });
  const regJson = await regR.json();
  console.log('  Register:', regJson.success ? 'OK' : regJson.detail);
  let token = regJson.access_token;

  // If already registered, login
  if (!token) {
    const loginR = await fetch(`${API}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_name: regData.provider_name, username: regData.username, password: regData.password })
    });
    const loginJson = await loginR.json();
    token = loginJson.access_token;
  }
  console.log('  Token:', token ? 'obtained' : 'FAILED');
  if (!token) { await browser.close(); return; }

  // Inject token BEFORE any navigation so it's available on first load
  await page.addInitScript((t) => {
    localStorage.setItem('provider-token', t);
  }, token);

  // === Create a client ===
  console.log('\n=== Create client via API ===');
  const cr = await fetch(`${API}/api/clients`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
    body: JSON.stringify({ name: '测试客户-某某制衣厂', industry: '服装生产' })
  }).then(r => r.json());
  console.log('  Client created:', cr.success ? 'OK id=' + cr.id : cr.detail);
  const clientId = cr.id;
  if (!clientId) { await browser.close(); return; }

  // === Step 1: Workbench ===
  console.log('\n=== Step 1: Workbench ===');
  await page.goto(`${BASE}/workbench?client_id=${clientId}`);
  await page.waitForTimeout(2500);

  const step1Text = await page.textContent('body');
  console.log('  Step1 loaded:', step1Text.includes('客户录入') || step1Text.includes('Step 1'));

  // Fill Step1 form via JS to avoid visibility issues
  const filled = await page.evaluate(() => {
    const nameEl = document.getElementById('s1-name');
    const indEl = document.getElementById('s1-industry');
    const demandEl = document.getElementById('s1-demand');
    if (!nameEl || !indEl || !demandEl) return 'ELEMENTS_NOT_FOUND';

    nameEl.value = '测试客户-某某制衣厂';

    // Set industry to 服装生产
    const opts = [...indEl.options];
    const targetOpt = opts.find(o => o.text.includes('服装'));
    if (targetOpt) indEl.value = targetOpt.value;

    demandEl.value = '管理样板/版房工序进度跟踪，各工序自动流转';
    return 'OK';
  });
  console.log('  Form filled via JS:', filled);

  // Verify values were set
  const checkVal = await page.evaluate(() => ({
    name: document.getElementById('s1-name')?.value,
    industry: document.getElementById('s1-industry')?.value,
    demand: document.getElementById('s1-demand')?.value
  }));
  console.log('  Values:', JSON.stringify(checkVal));

  // Click 保存 via JS to avoid overlay issues
  const saved = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')];
    const btn = btns.find(b => b.textContent.includes('保存'));
    if (btn) { btn.click(); return true; }
    return false;
  });
  console.log('  Save clicked:', saved);
  await page.waitForTimeout(500);

  // Click primary action via JS
  await page.evaluate(() => {
    const btn = document.getElementById('floating-primary');
    if (btn) btn.click();
  });
  await page.waitForTimeout(8000);

  const urlAfterS1 = page.url();
  console.log('  After S1 action URL:', urlAfterS1);

  // === Step 2 ===
  await page.waitForTimeout(2000);
  const step2Text = await page.textContent('body');
  console.log('\n=== Step 2: 调研准备 ===');
  console.log('  Step2 loaded:', step2Text.includes('PART 1') || step2Text.includes('调研准备'));
  console.log('  Has PART1:', step2Text.includes('公司背景') || step2Text.includes('company_background'));
  console.log('  Has PART3 questions:', step2Text.includes('必问问题') || step2Text.includes('痛点收敛'));

  // === Step 3 ===
  await page.evaluate(() => { document.querySelector('.step[data-page="3"]')?.click(); });
  await page.waitForTimeout(2000);
  console.log('\n=== Step 3: 沟通纪要 ===');
  const step3Text = await page.textContent('body');
  console.log('  Step3 loaded:', step3Text.includes('沟通纪要') || step3Text.includes('新增沟通'));
  await page.evaluate(() => {
    const el = document.getElementById('s3-note-text');
    if (el) el.value = '客户需要全流程管理，支持手机端操作。';
    const btns = [...document.querySelectorAll('button')];
    btns.find(b => b.textContent.includes('保存'))?.click();
  });
  await page.waitForTimeout(1000);
  const savedNote = await page.textContent('body');
  console.log('  Note saved:', savedNote.includes('已保存') || savedNote.includes('沉淀'));

  // === Step 4 ===
  await page.evaluate(() => { document.querySelector('.step[data-page="4"]')?.click(); });
  await page.waitForTimeout(2000);
  console.log('\n=== Step 4: 需求整理 ===');
  const step4Text = await page.textContent('body');
  console.log('  Step4 loaded:', step4Text.includes('需求整理'));

  // Click 重新生成 via JS
  const hasRegen4 = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')];
    const btn = btns.find(b => b.textContent.includes('重新生成'));
    if (btn) { btn.click(); return true; }
    return false;
  });
  if (hasRegen4) {
    await page.waitForTimeout(8000);
    const afterGen = await page.textContent('body');
    console.log('  Report generated:', afterGen.includes('核心痛点') || afterGen.includes('customer_info') || afterGen.includes('现状'));
  }

  // === Step 5 ===
  await page.evaluate(() => { document.querySelector('.step[data-page="5"]')?.click(); });
  await page.waitForTimeout(2000);
  console.log('\n=== Step 5: Demo生成 ===');
  const step5Text = await page.textContent('body');
  console.log('  Step5 loaded:', step5Text.includes('Demo') || step5Text.includes('智能表格'));

  const hasRegen5 = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')];
    const btn = btns.find(b => b.textContent.includes('重新生成'));
    if (btn) { btn.click(); return true; }
    return false;
  });
  if (hasRegen5) {
    await page.waitForTimeout(8000);
    const afterGen5 = await page.textContent('body');
    console.log('  Demo Schema generated:', afterGen5.includes('JSON') || afterGen5.includes('Schema') || afterGen5.includes('sheet'));
  }

  console.log('\n=== Console Errors ===');
  errors.length ? errors.forEach(e => console.log('ERR:', e)) : console.log('No console errors!');

  await browser.close();
  console.log('\n=== Test Complete ===');
})();
