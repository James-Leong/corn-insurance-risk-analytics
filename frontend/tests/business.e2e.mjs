import assert from 'node:assert/strict'
import { chromium } from 'playwright'

// Run against the local app with the backend available for the scenario integration check.
const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
const page = await context.newPage()
const errors = []
page.on('pageerror', e => errors.push(e.message))
const role = value => page.locator('.role-picker select').selectOption(value)
const overview = () => page.locator('nav button').first().click()
const records = () => page.locator('nav button').nth(1).click()
const detail = page.getByRole('region', { name: '业务详情' })
const tableRow = id => page.locator('.business-table tbody tr').filter({ hasText: id })
async function stat(label, value) {
  const card = page.locator('.metric-card').filter({has: page.getByText(label, {exact:true})})
  await page.waitForFunction(({label,value})=>[...document.querySelectorAll('.metric-card')].some(el=>el.querySelector('.metric-label')?.textContent===label && el.querySelector('.metric-value')?.textContent?.includes(value)), {label,value})
  assert.equal(await card.count(),1)
}
try {
  await page.goto(process.env.APP_URL || 'http://127.0.0.1:5173')
  await stat('本季保障数量','180')
  assert.equal(await page.locator('.business-table').count(),0)
  assert.equal(await page.getByRole('button',{name:'导出筛选结果 CSV'}).count(),0)
  assert.equal(await page.getByText('尚未接入个人保单').count(),0)
  // A home-page task opens the record page at the corresponding policy.
  await page.getByRole('button',{name:'查看 / 办理',exact:true}).click()
  assert.equal(await page.locator('nav button[aria-current="page"]').getAttribute('aria-label'),'我的保单')
  assert.equal(await page.locator('.metric-card').count(),0)
  assert.equal(await page.locator('.business-table tbody tr').count(),2)
  await detail.getByRole('heading',{name:'保单详情 · POL-001'}).waitFor()
  await detail.getByRole('button',{name:'提交模拟理赔申请'}).click()
  assert((await detail.innerText()).includes('待审核'))
  assert.equal(await detail.getByRole('button',{name:'提交模拟理赔申请'}).count(),0)
  await page.reload()
  await records()
  assert((await tableRow('POL-001').innerText()).includes('待审核'))

  await role('insurer')
  await stat('待审核案件','3')
  await records()
  await tableRow('POL-001').getByRole('button',{name:'查看详情'}).click()
  await detail.getByRole('button',{name:'模拟审核通过',exact:true}).click()
  await detail.getByRole('button',{name:'模拟支付赔款',exact:true}).click()
  assert.equal(await detail.getByRole('button',{name:'模拟支付赔款',exact:true}).count(),0)
  await overview()
  await stat('已支付赔付','82,000')
  await role('farmer')
  await stat('已到账赔付','15,000')

  // Seeded record parameters are carried into the existing API calculator.
  await records()
  await tableRow('POL-001').getByRole('button',{name:'查看详情'}).click()
  await detail.getByRole('button',{name:'带入保障试算'}).click()
  await page.waitForFunction(()=>document.querySelector('.payout-number')?.textContent?.includes('15,000'))
  assert.equal(await page.locator('input').first().inputValue(),'100')
  await page.locator('input').first().fill('-1')
  await page.getByRole('alert').filter({hasText:'请填写完整的非负数字'}).waitFor()
  assert((await page.locator('.payout-number').innerText()).includes('—'))

  await role('cooperative')
  await stat('成员参保率','75%')
  await page.getByRole('button',{name:'查看成员',exact:true}).click()
  await detail.getByRole('button',{name:'建立模拟保单'}).click()
  assert.equal(await detail.getByRole('button',{name:'建立模拟保单'}).count(),0)
  await overview()
  await stat('成员参保率','100%')
  await page.reload()
  await role('cooperative')
  await stat('成员参保率','100%')

  await role('authority')
  await stat('目标农户覆盖率','61.54%')
  assert.equal(await page.getByRole('heading',{name:'农业项目监管与政策落实'}).count(),1)
  assert.equal(await page.getByText('最近样本价格',{exact:true}).count(),0)
  await page.getByLabel('地区范围').selectOption('示范区 A')
  await stat('目标农户覆盖率','80%')
  await page.getByRole('button',{name:'查看执行明细 →'}).click()
  assert.equal(await page.locator('.business-table tbody tr').count(),1)
  await tableRow('PRJ-001').getByRole('button',{name:'查看项目'}).click()
  await detail.getByRole('button',{name:'模拟拨付剩余补贴'}).click()
  await overview()
  await stat('补贴预算执行率','100%')
  await page.reload()
  await role('authority')
  await page.getByLabel('地区范围').selectOption('示范区 A')
  await stat('补贴预算执行率','100%')
  await records()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button',{name:'导出筛选结果 CSV'}).click()
  const download = await downloadPromise
  const chunks=[]
  for await (const chunk of await download.createReadStream()) chunks.push(chunk)
  const csv=Buffer.concat(chunks).toString('utf8')
  assert(csv.includes('Mock演示数据'))
  assert(csv.includes('示范项目 A'))
  assert(!csv.includes('示范项目 B'))
  await page.getByLabel('搜索',{exact:true}).fill('不存在的项目')
  assert((await page.locator('.business-table').innerText()).includes('没有符合筛选条件的项目'))
  await page.getByLabel('搜索',{exact:true}).fill('')
  await page.getByLabel('台账状态',{exact:true}).selectOption('补贴待拨付')
  assert.equal(await page.locator('.business-table tbody tr button').count(),0)
  await page.getByLabel('台账状态',{exact:true}).selectOption('全部')

  // Calendar-day forecasts carry explicit dates; trading-day horizons must not
  // infer dates from weekdays or the browser's local timezone.
  let timeUnit = 'calendar_day'
  const dates = ['2028-02-29','2028-03-01','2028-03-02','2028-03-03','2028-03-04','2028-03-05','2028-03-06']
  await page.route('**/market/corn', route=>route.fulfill({json:{
    symbol:'测试行情',unit:'元/吨',provider:timeUnit==='calendar_day'?'mock':'uqer',warning:'',
    series:[{date:'2028-02-28',price:2400}],
    forecast_time_unit:timeUnit || undefined,
    forecast:dates.map((date,i)=>({step:i+1,...(timeUnit==='calendar_day'?{date}:{}),price:2400+i,lower:2380,upper:2420})),
  }}))
  await page.reload()
  await page.getByRole('button',{name:'玉米行情',exact:true}).click()
  await page.locator('.forecast-card').first().getByText('2028-02-29',{exact:true}).waitFor()
  assert((await page.locator('.forecast-card').nth(1).innerText()).includes('2028-03-01'))
  assert((await page.locator('.forecast-time-note').innerText()).includes('包含周末和节假日'))
  timeUnit='trading_day'
  await page.reload()
  await page.getByRole('button',{name:'玉米行情',exact:true}).click()
  await page.locator('.forecast-card').first().getByText('1 个交易日后',{exact:true}).waitFor()
  assert((await page.locator('.forecast-card').last().innerText()).includes('7 个交易日后'))
  assert.equal(await page.locator('.forecast-card').getByText('2028-02-29',{exact:true}).count(),0)
  timeUnit=''
  await page.reload()
  await page.getByRole('button',{name:'玉米行情',exact:true}).click()
  await page.locator('.forecast-card').first().getByText('预测时间待确认',{exact:true}).waitFor()
  assert(!(await page.locator('.forecast-grid').innerText()).includes('步估计'))
  await page.unroute('**/market/corn')
  await page.reload()

  // Desktop and narrow layouts, including the record pages and table scrolling.
  for(const width of [1440,390,320]) {
    await page.setViewportSize({width,height:900})
    for(const value of ['farmer','cooperative','insurer','authority']) {
      await role(value)
      await overview()
      assert.equal(await page.locator('.metric-card').count(),4)
      assert.equal(await page.locator('.business-table').count(),0)
      assert.equal(await page.getByLabel('搜索',{exact:true}).count(),0)
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overview overflow: ${width}/${value}`)
      await records()
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`horizontal overflow: ${width}/${value}`)
      assert.equal(await page.locator('.metric-card').count(),0)
      assert.equal(await page.locator('.content-grid').count(),0)
      assert.equal(await page.locator('.records-panel').count(),1)
    }
  }
  await page.setViewportSize({width:1440,height:1000})
  await page.getByRole('button',{name:'重置演示',exact:true}).click()
  await page.getByRole('button',{name:'确认重置',exact:true}).click()
  await overview()
  await stat('目标农户覆盖率','53.85%')
  await page.reload()
  await stat('本季保障数量','180')
  await stat('已到账赔付','0')
  await context.addInitScript(()=>localStorage.setItem('grainguard-business-demo-v1','{invalid'))
  await page.reload()
  await stat('本季保障数量','180')
  assert.deepEqual(errors,[])
  console.log('PASS: separate overview/record content for all roles, task-to-detail navigation, claims end-to-end, enrollment, cross-role statistics, subsidies, persistence/reset, CSV filters, calculator handoff, mobile layouts, invalid storage recovery')
} finally {
  await browser.close()
}
