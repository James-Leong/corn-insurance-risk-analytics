import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser = await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE ? {executablePath:process.env.BROWSER_EXECUTABLE} : {})})
const page = await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true})
let mode='empty';const calls=[],errors=[]
const metadata={schema_version:'comparison-v1',run_id:'test-run',comparison_group_id:'test-group',title:'测试报告',created_at:'2026-10-24',source_kind:'measured',label_kind:'rule_generated',run_status:'incomplete',data_start:'2025-12-31',data_end:'2026-10-23',warnings:['研究结果，不用于核赔'],protocol:{window_trading_days:20,rule_version:'rule-v1'},selection:{frozen:false,selected_method_id:null,reason_code:'insufficient_data'},released_partitions:['validation']}
const example={case_id:'case-a',valuation_date:'2026-07-01',contract_id:'c2701',guarantee_price:2300,quantity_tons:100,observed_payout:0,payout_cap:0,deductible_per_ton:0,outputs:[{method_id:'historical_blocks',claim_probability:0,conditional_mean_payout:null,expected_payout:0,p90_payout:null,p90_status:'not_validated'},{method_id:'glm_hurdle',claim_probability:null,expected_payout:null,p90_payout:null,p90_status:'unsupported',reason_code:'insufficient_data'},{method_id:'price_last',reference_price:2400,scenario_payout:0,p90_status:'unsupported'}]}
const models=[{method_id:'historical_blocks',model_version:'v1',release_state:'research_only',coverage:1,failure_count:0,metrics:[{metric_id:'expected_payout_rmse',value:0,unit:'CNY',direction:'lower_is_better'}]},{method_id:'glm_hurdle',model_version:null,release_state:'not_evaluated',coverage:0,failure_count:2,reason_code:'insufficient_data',metrics:[{metric_id:'expected_payout_rmse',value:null,unit:'CNY',direction:'lower_is_better',missing_reason:'insufficient_data'}]}]
await page.route('**/api/v1/comparisons/**',async route=>{
 const u=new URL(route.request().url());calls.push(u.pathname+u.search)
 if(mode==='error')return route.fulfill({status:503,json:{detail:{message:'研究结果包损坏，请联系维护人员'}}})
 if(u.pathname.endsWith('/groups'))return route.fulfill({json:{items:mode==='empty'?[]:[{comparison_group_id:'test-group',title:'测试比较组',run_count:1}],default_group_id:mode==='empty'?null:'test-group',data_mode:'measured'}})
 if(u.pathname.endsWith('/runs'))return route.fulfill({json:{items:[metadata]}})
 if(u.pathname.endsWith('/metrics'))return route.fulfill({json:{sample_count:2,date_count:2,models,selection:metadata.selection}})
 if(u.pathname.endsWith('/cases'))return route.fulfill({json:{items:[example,{...example,case_id:'case-b',contract_id:'c2703',outputs:[]}]}})
 if(u.pathname.endsWith('/evidence'))return route.fulfill({json:{view:u.searchParams.get('view'),items:[]}})
 if(u.pathname.endsWith('/export'))return route.fulfill({json:{metadata,partition:'validation'}})
 return route.fulfill({json:metadata})
})
page.on('pageerror',e=>errors.push(e.message))
try{
 await page.goto(process.env.APP_URL||'http://127.0.0.1:5173')
 assert.equal(await page.getByRole('button',{name:'模型评估',exact:true}).count(),0)
 await page.locator('.role-picker select').selectOption('insurer');await page.getByRole('button',{name:'模型评估',exact:true}).click()
 await page.getByRole('heading',{name:'尚无可比较的实测结果'}).waitFor()
 mode='error';await page.getByRole('button',{name:'刷新报告'}).click();await page.getByRole('alert').filter({hasText:'研究结果包损坏'}).waitFor()
 assert.equal(await page.getByRole('heading',{name:'尚无可比较的实测结果'}).count(),0)
 mode='populated';await page.getByRole('button',{name:'重试加载报告'}).click();await page.getByRole('heading',{name:'尚未指定可采用方法'}).waitFor()
 assert((await page.locator('.comparison-workspace').innerText()).includes('2025-12-31 — 2026-10-23'))
 assert((await page.locator('.comparison-details').first().innerText()).includes('0 元/吨 · 0 元'))
 await page.getByRole('tab',{name:'方法对照'}).click();const rows=page.locator('.comparison-table tbody tr')
 assert((await rows.nth(0).innerText()).includes('0%'));assert((await rows.nth(0).innerText()).includes('尚未通过独立验证'))
 assert((await rows.nth(1).innerText()).includes('不支持 P90'));assert(!(await rows.nth(1).innerText()).includes('0%'));assert.equal(await rows.count(),2)
 await page.getByRole('heading',{name:'价格情景参照'}).waitFor();await page.locator('.comparison-case-picker select').selectOption('case-b');assert.equal(await rows.count(),0)
 assert((await page.locator('.comparison-details').first().innerText()).includes('c2703'))
 await page.getByRole('tab',{name:'验证报告'}).click();await page.getByRole('heading',{name:'验证结论与选择依据'}).waitFor()
 assert.equal(await page.getByRole('option',{name:'冻结测试集',exact:true}).count(),0);assert((await page.locator('.comparison-table').innerText()).includes('覆盖不完整'))
 const pending=page.waitForEvent('download');await page.getByRole('button',{name:'下载报告 JSON'}).click();assert.equal((await pending).suggestedFilename(),'test-run-validation.json')
 assert(calls.some(c=>c.includes('/export?partition=validation&format=json')));assert(!calls.some(c=>c.includes('partition=test')))
 await page.locator('.role-picker select').selectOption('farmer');assert.equal(await page.locator('.comparison-workspace').count(),0);assert.deepEqual(errors,[])
 console.log('PASS comparison: role scope, empty/error, dates, zero/null, P90, price separation, case switch, sealed test, export')
}finally{await browser.close()}
