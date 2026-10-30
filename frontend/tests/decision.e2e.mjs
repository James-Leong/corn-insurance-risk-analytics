import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'
import { accountFor } from './account.mjs'

if (!process.env.PLATFORM_TEST_PASSWORD) throw new Error('Set PLATFORM_TEST_PASSWORD for isolated acceptance accounts.')

const browser = await chromium.launch({ headless: true,
  ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const failures = []
page.on('pageerror', error => failures.push(error.message))
page.on('console', message => { if (/Extraneous|Unhandled error/.test(message.text())) failures.push(message.text()) })
const appUrl = process.env.APP_URL || 'http://127.0.0.1:5173'
const apiUrl = process.env.API_URL || appUrl
async function read(path) {
  const token = await page.evaluate(() => sessionStorage.getItem('grainguard.session.v2'))
  const response = await fetch(`${apiUrl}/api/v2${path}`, { headers: { Authorization: `Bearer ${token}` } })
  assert.equal(response.status, 200)
  return response.json()
}
async function module(name) {
  const menu = page.getByRole('button', { name: '打开功能导航', exact: true })
  if (await menu.isVisible()) await menu.click()
  await page.getByTestId('module-nav').getByRole('button', { name, exact: true }).click()
}
const subpage = name => page.getByTestId('page-nav').getByRole('button', { name: new RegExp(name) }).click()
async function screenshot(name) {
  if (!process.env.SCREENSHOT_DIR) return
  await mkdir(process.env.SCREENSHOT_DIR, { recursive: true })
  await page.screenshot({ path: `${process.env.SCREENSHOT_DIR}/${name}.png`, fullPage: true, animations: 'disabled' })
}
try {
  await page.goto(appUrl)
  await page.getByLabel('账号', { exact: true }).fill(accountFor('operator'))
  await page.getByLabel('密码', { exact: true }).fill(process.env.PLATFORM_TEST_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('button', { name: '记录业务判断', exact: true }).waitFor()
  assert.equal(new URL(page.url()).hash, '#decision')
  assert.equal(await page.getByTestId('view-mode').count(), 0)
  for (const name of ['玉米态势', '投保与保单', '数据与研究', '风险转移与组合', '结算与赔付']) {
    assert.equal(await page.getByTestId('module-nav').getByRole('button', { name, exact: true }).count(), 1)
  }
  await page.getByRole('img', { name: '玉米指定合约历史结算价与保障价格', exact: true }).waitFor()
  const dashboard = await read('/decision/dashboard')
  assert.equal(dashboard.agri_risk.status, 'available')
  assert(dashboard.agri_risk.assessments.length >= 4)
  assert(dashboard.policy.items.length > 0)
  assert.equal(dashboard.agri_risk.latest_observation.origin_type, 'synthetic')
  await page.getByRole('group', { name: '待办范围', exact: true }).getByRole('button', { name: '团队待办', exact: true }).click()
  const homeTasks = await read('/workspace')
  if (homeTasks.tasks.length) {
    await page.getByLabel('首页待办', { exact: true }).locator('button.gg-task').first().click()
    await page.getByRole('dialog').waitFor()
    await page.getByRole('button', { name: '关闭业务详情', exact: true }).click()
    await page.getByRole('link', { name: '玉米态势首页', exact: true }).click()
    await page.getByRole('img', { name: '玉米指定合约历史结算价与保障价格', exact: true }).waitFor()
  }
  await screenshot('玉米态势首页')
  await subpage('期货看板')
  const selector = page.getByLabel('选择期货合约', { exact: true })
  await selector.waitFor()
  assert.equal(await selector.inputValue(), 'c2701')
  await page.getByRole('img', { name: '玉米具体合约K线及成交量', exact: true }).waitFor()
  const futures = await read('/decision/futures')
  if (futures.history.some(row => row.open_price != null && row.close_price != null && row.high_price != null && row.low_price != null)) {
    assert.equal(await page.getByRole('button', { name: 'K线', exact: true }).isDisabled(), false)
    assert(await page.locator('.gg-futures-chart rect').count() > 0)
  }
  const changed = page.waitForResponse(response => response.url().includes('/decision/futures?') && response.url().includes('ticker=c2609'))
  await selector.selectOption('c2609')
  assert.equal((await changed).status(), 200)
  await page.getByText('当前为对比合约', { exact: false }).waitFor()
  const restored = page.waitForResponse(response => response.url().includes('/decision/futures?') && response.url().includes('ticker=c2701'))
  await selector.selectOption('c2701')
  assert.equal((await restored).status(), 200)
  await page.getByRole('img', { name: '玉米具体合约K线及成交量', exact: true }).waitFor()
  await screenshot('期货看板')
  await subpage('农情与政策')
  await page.getByRole('heading', { name: '天气、土壤与灾害风险', exact: true }).waitFor()
  assert.equal(await page.locator('.gg-hazard-grid article').count(), 4)
  const riskValues = await page.locator('.gg-hazard-value').allTextContents()
  await page.getByLabel('选择农情区域', { exact: true }).selectOption('230200')
  assert.notDeepEqual(await page.locator('.gg-hazard-value').allTextContents(), riskValues)
  await page.getByLabel('选择农情区域', { exact: true }).selectOption('231200')
  await page.getByLabel('政策分类', { exact: true }).selectOption('insurance')
  assert.equal(await page.locator('.gg-policy-event').count(), 1)
  await page.getByRole('button', { name: '查看详情', exact: true }).click()
  await page.locator('.gg-policy-detail').waitFor()
  await page.getByLabel('政策分类', { exact: true }).selectOption('all')
  await page.getByLabel('政策国家', { exact: true }).selectOption('USA')
  assert.equal(await page.locator('.gg-policy-event').count(), 1)
  await page.getByLabel('政策国家', { exact: true }).selectOption('all')
  await screenshot('农情与政策')
  await module('风险转移与组合')
  await subpage('再保 / 对冲安排')
  await page.getByRole('heading', { name: '对冲方案与报价', exact: true }).waitFor()
  assert.equal(await page.getByRole('heading', { name: '已有再保安排与分出', exact: true }).count(), 1)
  assert(await page.getByRole('heading', { name: '对冲方案与报价', exact: true }).evaluate(element => {
    const reinsurance = [...document.querySelectorAll('h2')].find(node => node.textContent === '已有再保安排与分出')
    return !!(element.compareDocumentPosition(reinsurance) & Node.DOCUMENT_POSITION_FOLLOWING)
  }))
  assert.equal(await page.getByRole('button', { name: '新建对冲方案', exact: true }).count(), 1)
  await module('结算与赔付')
  await subpage('收付明细')
  await page.getByRole('heading', { name: '客户赔款与到账余额', exact: true }).waitFor()
  const workspace = await read('/workspace')
  const companyPayables = workspace.payables.filter(row => row.kind !== 'claim')
  const tables = await page.locator('table').allTextContents()
  for (const payable of companyPayables) assert(!tables.join('\n').includes(payable.id), `company payable leaked into customer claim view: ${payable.id}`)
  await page.getByRole('group', { name: '收付用途', exact: true }).getByRole('button', { name: '全部应付', exact: true }).click()
  await page.getByRole('heading', { name: '批准应付与可付余额', exact: true }).waitFor()
  assert.equal(await page.getByRole('heading', { name: '再保摊回 / 对冲回款', exact: true }).count(), 1)
  const payableSearch = page.getByLabel('搜索当前列表', { exact: true }).first()
  for (const payable of companyPayables) {
    await payableSearch.fill(payable.id)
    await page.locator('tbody tr').filter({ hasText: payable.id }).first().waitFor()
  }
  // Old links must resolve to the same complete workspace without a mode parameter.
  await page.goto(`${appUrl}/?view=guided#experiments`)
  await page.getByRole('heading', { name: '研究实验', exact: true }).waitFor()
  assert.equal(new URL(page.url()).searchParams.has('view'), false)
  await page.getByRole('link', { name: '玉米态势首页', exact: true }).click()
  assert.equal(new URL(page.url()).hash, '#decision')
  for (const [name, titles] of [
    ['投保与保单', ['业务总览', '投保批次', '保单详情']],
    ['数据与研究', ['玉米数据浏览', '研究实验', '研究报告']],
    ['风险转移与组合', ['责任组合', '再保 / 对冲安排', '订单执行']],
    ['结算与赔付', ['采价核赔', '收付明细', '对账结案']],
  ]) {
    await module(name)
    for (const title of titles) {
      await subpage(title)
      await page.getByRole('heading', { name: new RegExp(title) }).first().waitFor()
      assert(!/demo|演示|模拟|沙盒|未接入/i.test(await page.locator('main').innerText()), `internal status wording: ${name}/${title}`)
    }
  }
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 950 })
    await module('玉米态势')
    for (const title of ['态势总览', '期货看板', '农情与政策']) {
      await subpage(title)
      await page.getByRole('heading', { name: title === '态势总览' ? '玉米态势' : title, exact: true }).waitFor()
      assert(!/demo|演示|模拟|沙盒|未接入/i.test(await page.locator('main').innerText()), `internal status wording: ${title}`)
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow ${width}/${title}`)
    }
    if (width === 390) {
      await subpage('态势总览')
      await screenshot('移动玉米态势首页')
    }
  }
  assert.deepEqual(failures, [])
  console.log('PASS: 数据库态势首页、完整导航、区域切换、风险记录、政策筛选与详情、业务待办、K线、收付用途、界面文案、三种宽度、无运行异常')
} catch (error) {
  await screenshot('聚焦验收失败')
  throw error
} finally { await browser.close() }
