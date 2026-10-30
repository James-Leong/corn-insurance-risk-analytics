import assert from 'node:assert/strict'
import { chromium, request } from 'playwright'
import { accountFor } from './account.mjs'

// Run against an isolated acceptance service. Business commands below are intercepted.
const appUrl = process.env.APP_URL
const password = process.env.PLATFORM_TEST_PASSWORD
assert(appUrl, 'APP_URL must point to an isolated acceptance service')
assert(password, 'Provide the acceptance account password through PLATFORM_TEST_PASSWORD')
const api = await request.newContext({ baseURL: appUrl })
const browser = await chromium.launch({ headless: true,
  ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}) })
const errors = []
async function session(username) {
  const response = await api.post('/api/v2/session', { data: { username, password } })
  assert.equal(response.status(), 200, `Unable to sign in acceptance user ${username}`)
  return response.json()
}
async function signedInPage(signedIn, workspace) {
  const context = await browser.newContext()
  await context.addInitScript(token => sessionStorage.setItem('grainguard.session.v2', token), signedIn.token)
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/v2/workspace?*', route => route.fulfill({ json: workspace }))
  await page.route('**/api/v2/workspace/commands', route => route.fulfill({
    status: 400, json: { detail: 'Regression checks do not persist business commands' },
  }))
  return page
}
try {
  const operator = await session(accountFor('operator'))
  const reviewer = await session(accountFor('reviewer'))
  const response = await api.get('/api/v2/workspace?project_id=PRJ-001', {
    headers: { Authorization: `Bearer ${operator.token}` },
  })
  assert.equal(response.status(), 200)
  const workspace = await response.json()
  const fixtures = structuredClone(workspace)
  fixtures.applications = ['draft', 'approved', 'rejected', 'withdrawn'].map((status, i) => ({
    id: `APP-REVIEW-${i}`, version: 1, status, premium_due: (i + 1) * 100,
    premium_received: 0, insured_name: `验收申请${i + 1}`, region: '黑龙江省绥化市', tons: 10,
  }))
  fixtures.claims = [
    { id: 'CLM-REVIEW-ZERO', version: 1, status: 'pending_review',
      policy_id: fixtures.policies[0]?.id, rule_amount: 900, assessed_amount: 0, approved_amount: 0 },
    { id: 'CLM-REVIEW-REJECTED', version: 2, status: 'rejected',
      policy_id: fixtures.policies[0]?.id, rule_amount: 900, assessed_amount: 0, approved_amount: 0 },
  ]

  const reviewerPage = await signedInPage(reviewer, fixtures)
  await reviewerPage.goto(`${appUrl}/#overview`)
  const outstanding = reviewerPage.locator('.gg-kpis article').filter({ hasText: '保费待收余额' })
  await outstanding.waitFor()
  assert.equal((await outstanding.locator('strong').innerText()).replace(/\s/g, ''), '300元')
  await reviewerPage.getByTestId('page-nav').getByRole('button', { name: '投保批次 / 申请', exact: true }).click()
  assert.equal(await reviewerPage.getByRole('button', { name: '新建投保申请', exact: true }).count(), 0)
  assert.equal(await reviewerPage.getByRole('button', { name: '批量导入', exact: true }).count(), 0)
  await reviewerPage.getByTestId('module-nav').getByRole('button', { name: '结算与赔付', exact: true }).click()
  await reviewerPage.locator('tbody tr').filter({ hasText: 'CLM-REVIEW-ZERO' }).click()
  await reviewerPage.getByRole('button', { name: '复核赔款核定', exact: true }).click()
  assert.equal(await reviewerPage.getByRole('dialog', { name: '复核赔款核定', exact: true }).getByLabel('批准金额（元）').inputValue(), '0')
  await reviewerPage.context().close()

  const operatorPage = await signedInPage(operator, fixtures)
  const dashboardResponse = await api.get('/api/v2/decision/dashboard?project_id=PRJ-001', {
    headers: { Authorization: `Bearer ${operator.token}` },
  })
  assert.equal(dashboardResponse.status(), 200)
  const dashboard = await dashboardResponse.json()
  const observations = [
    { id: 'OBS-SUIHUA', region_code: '231200', region_name: '黑龙江省绥化市', release_id: 'ENV-SUIHUA' },
    { id: 'OBS-QIQIHAR', region_code: '230200', region_name: '黑龙江省齐齐哈尔市', release_id: 'ENV-QIQIHAR' },
  ].map(observation => ({ observation_date: '2026-10-23', temperature_c: 10, rainfall_mm: 4,
    wind_speed_ms: 5, soil_water_content: 0.3, soil_saturation: 0.6, soil_depth_cm: '0—20',
    growth_stage_name: '成熟期', ...observation }))
  const risks = observations.map((observation, i) => ({
    id: `RISK-${observation.region_code}`, region_code: observation.region_code,
    hazard_type: 'lodging', hazard_name: '玉米倒伏', risk_level: 'medium', probability: 0.2 + i * 0.1,
    model_version: `regional-risk-${i + 1}`, as_of: `2026-10-23T0${8 + i}:00:00+08:00`,
    valid_until: '2026-10-30T08:00:00+08:00', recommendation: '核查地块生育期与风速',
  }))
  dashboard.agri_risk = { ...dashboard.agri_risk, status: 'available',
    latest_observation: observations[0], regional_observations: observations,
    assessments: [risks[0]], all_assessments: risks }
  await operatorPage.route('**/api/v2/decision/dashboard?*', route => route.fulfill({ json: dashboard }))
  await operatorPage.goto(`${appUrl}/#agri-risk`)
  await operatorPage.getByLabel('选择农情区域', { exact: true }).selectOption('230200')
  await operatorPage.getByRole('button', { name: '记录业务判断', exact: true }).click()
  const dialog = operatorPage.getByRole('dialog', { name: '记录人工承保判断', exact: true })
  assert.equal(await dialog.getByLabel('判断适用地区').inputValue(), '黑龙江省齐齐哈尔市')
  await dialog.getByLabel('办理依据与说明').fill('按所选产区核对风险依据')
  const command = operatorPage.waitForRequest(request => request.url().endsWith('/workspace/commands'))
  await dialog.getByRole('button', { name: '保存只读判断记录', exact: true }).click()
  const { payload } = (await command).postDataJSON()
  assert.equal(payload.region, '黑龙江省齐齐哈尔市')
  assert.equal(payload.source_context.region_code, '230200')
  assert.equal(payload.source_context.environment_observation_id, 'OBS-QIQIHAR')
  assert.equal(payload.source_context.environment_version, 'ENV-QIQIHAR')
  assert.equal(payload.source_context.risk_model_version, 'regional-risk-2')
  assert.equal(payload.source_context.risk_as_of, risks[1].as_of)
  assert.deepEqual(payload.source_context.risk_assessments.map(risk => risk.id), ['RISK-230200'])
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await operatorPage.getByTestId('module-nav').getByRole('button', { name: '结算与赔付', exact: true }).click()
  await operatorPage.locator('tbody tr').filter({ hasText: 'CLM-REVIEW-REJECTED' }).click()
  await operatorPage.getByRole('button', { name: '修改并重新提交', exact: true }).click()
  const resubmit = operatorPage.getByRole('dialog', { name: '修改并重新提交赔款核定', exact: true })
  assert.equal(await resubmit.getByLabel('更正后累计核定额（元）').inputValue(), '0')
  await resubmit.getByLabel('办理依据与说明').fill('按复核退回意见补充核定依据')
  const correction = operatorPage.waitForRequest(request => request.url().endsWith('/workspace/commands'))
  await resubmit.getByRole('button', { name: '确认提交', exact: true }).click()
  const correctionBody = (await correction).postDataJSON()
  assert.equal(correctionBody.command, 'claim.correct')
  assert.equal(correctionBody.target_id, 'CLM-REVIEW-REJECTED')
  assert.equal(correctionBody.expected_version, 2)
  assert.equal(correctionBody.payload.assessed_amount, 0)
  assert.deepEqual(errors, [])
  console.log('PASS: 零赔复核默认额、复核岗入口授权、撤回拒保待收排除、切换产区判断依据一致、退回核定修改重提')
} finally {
  await browser.close()
  await api.dispose()
}
