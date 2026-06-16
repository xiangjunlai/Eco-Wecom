import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  // Track all requests/responses
  page.on('response', async r => {
    console.log('  <-', r.status(), r.url().replace('http://localhost:8000',''));
  });

  await page.goto('http://localhost:9090/login.html');
  await page.waitForTimeout(500);

  // Login
  await page.click('a:has-text("立即注册")');
  await page.waitForTimeout(300);
  await page.fill('#reg-provider', '测试Reg用户');
  await page.fill('#reg-code', 'TESTREG1');
  await page.fill('#reg-username', 'pw_test');
  await page.fill('#reg-password', 'Test1234!');
  await page.fill('#reg-password2', 'Test1234!');
  await page.click('#btn-register');

  await page.waitForTimeout(5000);
  console.log('URL after register:', page.url());

  // Check what's on the page
  const loading = await page.$('#loading');
  if (loading) {
    const cls = await loading.getAttribute('class');
    console.log('Loading class:', cls);
  }

  const bodyText = await page.textContent('body');
  console.log('Has 客户列表:', bodyText.includes('客户列表'));
  console.log('Has 新建:', bodyText.includes('新建'));

  await browser.close();
})();
