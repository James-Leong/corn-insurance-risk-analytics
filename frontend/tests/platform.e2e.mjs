import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'
import { accountFor } from './account.mjs'

if (!process.env.PLATFORM_TEST_PASSWORD) throw new Error('Set PLATFORM_TEST_PASSWORD for isolated acceptance accounts.')
assert.equal(process.env.PLATFORM_TEST_ALLOW_WRITES, 'isolated', 'Full business acceptance requires an explicitly confirmed, isolated MySQL instance.')

// Uses a running application, real local market snapshots, and durable API writes.
// Use an isolated MySQL acceptance instance and existing users.
const appUrl = process.env.APP_URL || 'http://127.0.0.1:5173'
const apiUrl = process.env.API_URL || appUrl
const password = process.env.PLATFORM_TEST_PASSWORD
const projectId = 'PRJ-001'
const suffix = randomUUID().slice(0, 8)
const sessions = {}
async function request(path, { user = 'operator', body, status = 200 } = {}) {
  const response = await fetch(`${apiUrl}/api/v2${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', ...(sessions[user] ? { Authorization: `Bearer ${sessions[user]}` } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  const result = await response.json()
  assert.equal(response.status, status, `${path}: ${JSON.stringify(result)}`)
  return result
}
for (const role of ['operator', 'reviewer', 'customer']) {
  const username = accountFor(role)
  const session = await request('/session', { body: { username, password } })
  sessions[role] = session.token
  assert.equal(session.user.role, role)
}
await request('/workspace', { user: 'anonymous', status: 401 })
let workspace = await request(`/workspace?project_id=${projectId}`)
assert.equal(workspace.storage_backend, 'mysql')
assert.equal(workspace.execution_mode, 'simulation')
const entity = (collection, id) => workspace[collection].find(row => row.id === id)
async function command(name, payload = {}, { user = 'operator', target, requestId = randomUUID(), status = 200 } = {}) {
  const body = { command: name, project_id: projectId, request_id: requestId, payload,
    ...(target ? { target_id: target.id, expected_version: target.version } : {}) }
  const result = await request('/workspace/commands', { user, body, status })
  if (status === 200) workspace = result.snapshot
  return { ...result, body }
}
const dashboard = await request(`/decision/dashboard?project_id=${projectId}`)
assert.equal(dashboard.context_only, true)
assert.equal(dashboard.not_claim_trigger, true)
assert.equal(dashboard.market.status, 'available')
assert.equal(dashboard.product.contract, 'c2701')
const decisionResult = await command('decision.record', {
  region: '黑龙江省·绥化市', disposition: 'proceed', reason: '竞标验收人工判断：保留资料版本，交核保复核。',
  source_context: dashboard.source_context,
})
const applicationResult = await command('application.create', {
  applicant_name: `验收合作社-${suffix}`, insured_name: `验收合作社-${suffix}`,
  tons: 10, area_mu: 20, region: '黑龙江省·绥化市', phone: '13800002026',
  period_start: '2026-07-01', period_end: '2026-10-23', terms_confirmed: true,
  materials: ['种植证明（验收样例）', '投保清单（验收样例）'],
  decision_id: decisionResult.result.id,
})
const appId = applicationResult.result.id
assert.equal(entity('applications', appId).decision_snapshot.id, decisionResult.result.id)
const originalDraft = entity('applications', appId)
await command('application.submit', { terms_confirmed: true, materials: originalDraft.materials }, { target: originalDraft })
await command('application.review', { decision: 'approved', reason: '验收复核' }, { target: entity('applications', appId), status: 403 })
await command('application.update', { tons: 10 }, { target: originalDraft, status: 409 })
await command('application.review', { decision: 'approved', reason: '验收复核' }, { user: 'reviewer', target: entity('applications', appId) })
await command('application.premium', { amount: 600, reference: `SIM-PREMIUM-${suffix}` }, { target: entity('applications', appId) })
await command('policy.issue', {}, { target: entity('applications', appId) })
assert.equal(entity('applications', appId).status, 'issuing')
await command('policy.query', { outcome: 'unknown' }, { target: entity('applications', appId) })
await command('policy.query', { outcome: 'confirmed' }, { target: entity('applications', appId) })
const policyId = entity('applications', appId).policy_id
assert.equal(entity('policies', policyId).tons, 10)
await command('reinsurance.allocate', { policy_id: policyId, ratio: 0.3, reference: `SIM-RI-${suffix}` }, { user: 'reviewer', target: entity('reinsurance', 'RI-001') })
const planResult = await command('hedge.plan', {
  name: `验收方案-${suffix}`, policy_ids: [policyId], tons: 5, tool: 'otc_put',
  strike_price: 2400, premium_per_ton: 40, reason: '本次演示责任保护',
})
const planId = planResult.result.id
await command('hedge.quote', { premium_per_ton: 40, reference: `SIM-QUOTE-${suffix}` }, { target: entity('plans', planId) })
await command('hedge.review', { decision: 'approved', reason: '已核对演示责任' }, { user: 'reviewer', target: entity('plans', planId) })
const executionResult = await command('hedge.submit', {}, { target: entity('plans', planId) })
const executionId = executionResult.result.id
assert.equal(entity('executions', executionId).reserved_tons, 5)
await command('hedge.query', { outcome: 'unknown' }, { target: entity('executions', executionId) })
assert.equal(entity('executions', executionId).reserved_tons, 5)
await command('hedge.confirm', { cumulative_tons: 2, event_id: `SIM-FILL-1-${suffix}`, final: false }, { user: 'reviewer', target: entity('executions', executionId) })
assert.equal(entity('executions', executionId).reserved_tons, 3)
await command('hedge.confirm', { cumulative_tons: 5, event_id: `SIM-FILL-2-${suffix}`, final: true }, { user: 'reviewer', target: entity('executions', executionId) })
assert.equal(entity('executions', executionId).reserved_tons, 0)
const hedge = workspace.hedges.find(row => row.execution_id === executionId)
assert(hedge, 'confirmed execution creates a hedge contract')
const hedgePremiums = workspace.payables.filter(row => row.kind === 'hedge_premium' && row.source_id === hedge.id)
assert.equal(hedgePremiums.length, 1)
assert.equal(hedgePremiums[0].amount, 200, 'partial fills update one actual premium liability')
await command('hedge.allocate', { policy_id: policyId, tons: 5 }, { target: hedge })
const fixingResult = await command('fixing.prepare', { policy_id: policyId })
const fixingId = fixingResult.result.id
assert.equal(entity('fixings', fixingId).status, 'pending_review', 'actual local observations must be complete')
assert(entity('fixings', fixingId).source_version.length === 64)
assert(entity('fixings', fixingId).observations.every(row => row.published_at == null))
await command('fixing.confirm', { reason: '核对本地结算价快照' }, { user: 'reviewer', target: entity('fixings', fixingId) })
const claimResult = await command('claim.calculate', { policy_id: policyId, fixing_id: fixingId })
const claimId = claimResult.result.id
assert.equal(workspace.payables.filter(row => row.claim_id === claimId).length, 0)
await command('claim.review', { decision: 'approved', reason: '依锁定规则核赔' }, { user: 'reviewer', target: entity('claims', claimId) })
let payable = workspace.payables.find(row => row.claim_id === claimId)
assert(payable?.amount > 0)
const payoutAmount = payable.amount
const paymentResult = await command('payment.create', { amount: payoutAmount, reference: `SIM-PAY-${suffix}` }, { target: payable })
const paymentId = paymentResult.result.id
assert.equal(entity('payables', payable.id).available_amount, 0)
await command('payment.create', { amount: 1, reference: `SIM-DUP-${suffix}` }, { target: entity('payables', payable.id), status: 409 })
await command('payment.review', { decision: 'approved', reason: '已核对演示收款信息' }, { user: 'reviewer', target: entity('payments', paymentId) })
const half = Math.floor(payoutAmount * 50) / 100
const partial = await command('payment.receipt', { outcome: 'partial', cumulative_amount: half, event_id: `SIM-PARTIAL-${suffix}`, reference: '模拟部分支付' }, { target: entity('payments', paymentId) })
payable = entity('payables', payable.id)
assert.equal(payable.paid_amount, half)
assert.equal(payable.reserved_amount, Math.round((payoutAmount - half) * 100) / 100)
await command('payment.receipt', { outcome: 'unknown', event_id: `SIM-UNKNOWN-${suffix}`, reference: '模拟查询仍未知' }, { target: entity('payments', paymentId) })
await command('payment.receipt', { outcome: 'success', cumulative_amount: payoutAmount, event_id: `SIM-SUCCESS-${suffix}`, reference: '模拟到账' }, { target: entity('payments', paymentId) })
assert.equal(entity('payables', payable.id).paid_amount, payoutAmount)
// A retry returns the current aggregate and never restores the older partial state.
const retry = await request('/workspace/commands', { body: partial.body })
assert.equal(retry.snapshot.payables.find(row => row.id === payable.id).paid_amount, payoutAmount)
assert.equal(retry.snapshot.revision, workspace.revision)
assert(workspace.recoveries.some(row => row.claim_id === claimId), 'original claim payment is independent of outstanding recoveries')
const customer = await request('/workspace', { user: 'customer' })
assert(customer.applications.every(row => row.customer_id === 'USR-CUSTOMER'))
assert.equal(customer.plans.length, 0)
assert.equal(customer.decision_records.length, 0)
assert(customer.applications.every(row => !('decision_snapshot' in row) && !('decision_id' in row)))
assert.equal(customer.claims.find(row => row.id === claimId).paid_amount, payoutAmount)
assert.equal(customer.claims.find(row => row.id === claimId).unpaid_amount, 0)
await request('/data/catalog', { user: 'customer', status: 403 })
await request('/decision/dashboard', { user: 'customer', status: 403 })
const readiness = await request('/decision/risk-assessments', { body: {
  project_id: projectId, region_code: '231200', region_name: '黑龙江省绥化市', crop: 'maize',
  as_of: '2026-10-25T12:00:00+08:00', hazard_types: ['lodging', 'waterlogging'], horizon_days: 7,
} })
assert.equal(readiness.status, 'not_ready')
assert.equal(readiness.risk_level, null)
assert.equal(readiness.probability, null)

const catalog = await request('/data/catalog')
const market = catalog.series.find(row => row.id.includes('c2701') && row.id.includes('settlePrice'))
assert(market, 'market catalog exposes real contract settlement prices')
const dataset = await request('/research/datasets', { status: 201, body: {
  name: `验收快照-${suffix}`, series_id: market.id, as_of: '2026-10-25', project_id: projectId,
} })
assert(dataset.row_count > 40)
const factor = await request('/research/factors', { status: 201, body: { name: `验收滞后-${suffix}`, operator: 'lag', input_field: 'value', lag: 1 } })
const run = await request('/research/runs', { status: 201, body: {
  name: `验收实验-${suffix}`, dataset_id: dataset.id, factor_ids: [factor.id], model_id: 'naive_last', target: 'price',
} })
const report = await request('/research/reports', { status: 201, body: {
  name: `验收报告-${suffix}`, run_id: run.id, conclusion: '验收用历史回放结果，仅供本次演示分析。', share_scope: 'team', project_id: projectId,
} })
assert.equal((await request(`/research/reports/${report.id}`, { user: 'reviewer' })).run_id, run.id)
if (process.env.API_ONLY === '1') {
  console.log('PASS: 投保、风险转移、核赔付款与研究 API 完整链路')
  process.exit(0)
}

const browser = await chromium.launch({ headless: true,
  ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
const modules = [
  ['玉米态势', ['态势总览', '期货看板', '农情与政策']],
  ['投保与保单', ['业务总览', '投保批次', '保单详情']],
  ['数据与研究', ['玉米数据', '研究实验', '研究报告']],
  ['风险转移与组合', ['责任组合', '再保', '订单执行']],
  ['结算与赔付', ['采价核赔', '收付明细', '对账结案']],
]
try {
  await page.goto(appUrl)
  await page.getByLabel('账号', { exact: true }).fill(accountFor('operator'))
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByTestId('module-nav').waitFor()
  for (const title of ['玉米态势', '投保与保单', '数据与研究', '风险转移与组合', '结算与赔付']) {
    assert.equal(await page.getByTestId('module-nav').getByRole('button', { name: title, exact: true }).count(), 1)
  }
  assert.equal(await page.getByTestId('view-mode').count(), 0)
  assert.equal(new URL(page.url()).hash, '#decision')
  await page.getByRole('button', { name: '记录业务判断', exact: true }).click()
  const decisionDialog = page.getByRole('dialog', { name: '记录人工承保判断', exact: true })
  await decisionDialog.getByLabel('人工判断').selectOption('proceed')
  await decisionDialog.getByLabel('办理依据与说明').fill(`界面竞标判断-${suffix}，根据已显示快照补充人工意见。`)
  let guidedRequest = page.waitForResponse(response => response.url().endsWith('/workspace/commands') && response.request().postDataJSON().command === 'decision.record')
  await decisionDialog.getByRole('button', { name: '保存只读判断记录', exact: true }).click()
  const savedDecision = await (await guidedRequest).json()
  assert(savedDecision.result.id)
  await page.getByRole('button', { name: '带入投保申请', exact: true }).click()
  const guidedApplication = page.getByRole('dialog', { name: '新建投保申请', exact: true })
  assert.equal(await guidedApplication.getByLabel('关联人工判断编号').inputValue(), savedDecision.result.id)
  await guidedApplication.getByLabel('投保人', { exact: false }).first().fill(`界面竞标合作社-${suffix}`)
  await guidedApplication.getByLabel('被保险人').fill(`界面竞标合作社-${suffix}`)
  await guidedApplication.getByLabel('联系电话').fill('13800002026')
  await guidedApplication.getByRole('checkbox').check()
  guidedRequest = page.waitForResponse(response => response.url().endsWith('/workspace/commands') && response.request().postDataJSON().command === 'application.create')
  await guidedApplication.getByRole('button', { name: '保存申请草稿', exact: true }).click()
  const savedApplication = await (await guidedRequest).json()
  assert.equal(savedApplication.result.decision_id, savedDecision.result.id)
  await guidedApplication.waitFor({ state: 'hidden' })
  const closeDetail = page.getByRole('button', { name: '关闭业务详情', exact: true })
  if (await closeDetail.count()) await closeDetail.click()
  for (const [moduleName, pages] of modules) {
    await page.getByTestId('module-nav').getByRole('button', { name: moduleName, exact: true }).click()
    for (const title of pages) {
      await page.getByTestId('page-nav').getByRole('button', { name: new RegExp(title) }).click()
      await page.waitForTimeout(100)
      assert(await page.locator('main').innerText())
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `desktop overflow: ${title}`)
    }
  }
  await page.getByTestId('module-nav').getByRole('button', { name: '投保与保单', exact: true }).click()
  await page.getByTestId('page-nav').getByRole('button', { name: /投保批次/ }).click()
  const search = page.getByLabel('搜索当前列表', { exact: true }).first()
  await search.fill(`验收合作社-${suffix}`)
  await page.locator('tbody tr').filter({ hasText: `验收合作社-${suffix}` }).first().waitFor()
  await page.reload()
  await page.getByTestId('module-nav').waitFor()
  await page.getByTestId('page-nav').getByRole('button', { name: /投保批次/ }).click()
  await page.getByLabel('搜索当前列表', { exact: true }).first().fill(`验收合作社-${suffix}`)
  await page.locator('tbody tr').filter({ hasText: `验收合作社-${suffix}` }).first().waitFor()
  // Exercise real browser forms too; this catches drift from strict API schemas.
  await page.getByTestId('module-nav').getByRole('button', { name: '数据与研究', exact: true }).click()
  await page.getByTestId('page-nav').getByRole('button', { name: /玉米数据/ }).click()
  await page.getByLabel('选择数据指标').selectOption(market.id)
  const queried = page.waitForResponse(response => response.url().endsWith('/data/query') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '查询', exact: true }).click()
  assert.equal((await queried).status(), 200)
  await page.getByRole('button', { name: '带入研究并冻结快照' }).click()
  async function submitForm(button, path) {
    const responsePromise = page.waitForResponse(response => response.url().endsWith(path) && response.request().method() === 'POST')
    await page.getByRole('dialog').getByRole('button', { name: button, exact: true }).click()
    const response = await responsePromise
    assert.equal(response.status(), 201, `UI ${path}: ${await response.text()}`)
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    return response.json()
  }
  await page.getByRole('dialog').getByLabel('数据集名称').fill(`界面快照-${suffix}`)
  await submitForm('保存只读快照', '/research/datasets')
  await page.getByTestId('page-nav').getByRole('button', { name: /研究实验/ }).click()
  await page.getByRole('button', { name: '新建研究因子' }).click()
  await page.getByRole('dialog').getByLabel('因子名称').fill(`界面因子-${suffix}`)
  await submitForm('保存因子版本', '/research/factors')
  await page.getByRole('button', { name: '新建研究实验' }).click()
  await page.getByRole('dialog').getByLabel('实验名称').fill(`界面实验-${suffix}`)
  const uiRun = await submitForm('运行并历史验证', '/research/runs')
  assert.equal(uiRun.status, 'succeeded')
  await page.getByRole('button', { name: '保存研究报告', exact: true }).click()
  await page.getByRole('dialog').getByLabel('报告名称').fill(`界面报告-${suffix}`)
  await submitForm('保存报告版本', '/research/reports')
  await page.getByTestId('page-nav').getByRole('button', { name: /玉米数据/ }).click()
  await page.getByRole('button', { name: '标准文件导入', exact: true }).click()
  const importDialog = page.getByRole('dialog', { name: '导入玉米外部数据', exact: true })
  await importDialog.getByLabel('数据名称').fill(`供需验收样例-${suffix}`)
  await importDialog.getByLabel('来源标识').fill(`acceptance_${suffix}`)
  await importDialog.getByLabel('原文／原始文件链接').fill('https://example.com/fixture')
  await importDialog.getByLabel('来源发布日期').fill('2026-10-01')
  await importDialog.getByLabel('发布批次／修订号').fill('fixture-v1')
  await importDialog.getByLabel('数据类型').selectOption('supply_demand')
  await importDialog.getByLabel('数据内容').fill('entity_code,metric,marketing_year,period_start,period_end,value\nUSA,domestic_consumption,2025/26,2025-09-01,2026-08-31,80\nUSA,exports_my,2025/26,2025-09-01,2026-08-31,20')
  await importDialog.getByLabel('仅用于研究参考，不作为合同采价依据').check()
  async function previewImport() {
    const pending = page.waitForResponse(response => response.url().endsWith('/data/imports') && response.request().method() === 'POST')
    await importDialog.getByRole('button', { name: '校验并预览', exact: true }).click()
    const response = await pending
    assert.equal(response.status(), 201, await response.text())
    await importDialog.getByRole('heading', { name: '预览通过，尚未写入数据目录', exact: true }).waitFor()
  }
  await previewImport()
  await importDialog.getByLabel('发布批次／修订号').fill('fixture-v2')
  assert.equal(await importDialog.getByRole('button', { name: '确认导入', exact: true }).isDisabled(), true)
  await previewImport()
  const importedResponse = page.waitForResponse(response => response.url().endsWith('/data/imports') && response.request().method() === 'POST')
  await importDialog.getByRole('button', { name: '确认导入', exact: true }).click()
  const importResponse = await importedResponse
  assert.equal(importResponse.status(), 201, await importResponse.text())
  const importedData = await importResponse.json()
  assert.equal(importedData.release_identity.is_fixture, true)
  await importDialog.waitFor({ state: 'hidden' })
  // Hold an older market response while a newer supply/demand query completes.
  let markSlowReached, releaseSlow, markSlowDone
  const slowReached = new Promise(resolve => { markSlowReached = resolve })
  const slowGate = new Promise(resolve => { releaseSlow = resolve })
  const slowDone = new Promise(resolve => { markSlowDone = resolve })
  let holdMarket = true
  await page.route('**/api/v2/data/query', async route => {
    if (holdMarket && route.request().postDataJSON().series_id === market.id) {
      holdMarket = false
      const response = await route.fetch()
      markSlowReached()
      await slowGate
      await route.fulfill({ response })
      markSlowDone()
    } else await route.continue()
  })
  await page.getByLabel('选择数据指标').selectOption(market.id)
  await page.getByRole('button', { name: '查询', exact: true }).click()
  await slowReached
  await page.getByLabel('选择数据指标').selectOption('casde.CHN.export_share')
  const newQuery = page.waitForResponse(response => response.url().endsWith('/data/query') && response.request().postDataJSON().series_id === 'casde.CHN.export_share')
  await page.getByRole('button', { name: '查询', exact: true }).click()
  assert.equal((await newQuery).status(), 200)
  releaseSlow()
  await slowDone
  await page.waitForFunction(() => document.querySelector('.gg-series-value strong')?.textContent?.includes('0.0033'))
  assert((await page.locator('.gg-series-value').innerText()).includes('%'))
  assert((await page.locator('.gg-series-foot').innerText()).includes('4 个观测'))
  await page.unroute('**/api/v2/data/query')
  await page.getByTestId('module-nav').getByRole('button', { name: '投保与保单', exact: true }).click()
  await page.getByTestId('page-nav').getByRole('button', { name: /投保批次/ }).click()
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `mobile overflow ${width}`)
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true })
    await page.getByTestId('page-nav').getByRole('button', { name: /业务总览/ }).click()
    await page.screenshot({ path: `${process.env.SCREENSHOT_DIR}/四模块工作台.png`, fullPage: true })
  }
  await page.getByTestId('module-nav').getByRole('button', { name: '结算与赔付', exact: true }).click()
  await page.getByTestId('page-nav').getByRole('button', { name: /对账结案/ }).click()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出项目档案', exact: true }).click()
  const chunks = []
  for await (const chunk of await (await downloadPromise).createReadStream()) chunks.push(chunk)
  const exported = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  assert.equal(exported.execution_mode, 'simulation')
  assert(exported.applications.some(row => row.id === appId))
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await page.getByLabel('账号', { exact: true }).fill(accountFor('customer'))
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('heading', { name: '我的投保申请', exact: true }).waitFor()
  assert.equal(await page.getByTestId('module-nav').count(), 0)
  assert.equal(await page.getByRole('button', { name: '我的保单与进度', exact: true }).count(), 1)
  await page.getByRole('button', { name: '我的保单与进度', exact: true }).click()
  await page.getByRole('heading', { name: '我的赔付进度', exact: true }).waitFor()
  await page.locator('tbody tr').filter({ hasText: claimId }).first().waitFor()
  assert.deepEqual(errors, [])
  console.log('PASS: 四模块导航、角色隔离、投保出单、版本冲突、分批成交、真实采价、核赔付款、回执幂等、研究报告、持久化和移动布局')
} catch (error) {
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true })
    await page.screenshot({ path: `${process.env.SCREENSHOT_DIR}/验收失败.png`, fullPage: true })
    console.error((await page.locator('body').innerText()).slice(-6000))
  }
  throw error
} finally {
  await browser.close()
}
