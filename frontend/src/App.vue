<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import BusinessWorkspace from './components/BusinessWorkspace.vue'
import ModelComparisonWorkspace from './components/ModelComparisonWorkspace.vue'
import type { Policy } from './mockBusiness'
import MarketWorkspace from './components/MarketWorkspace.vue'
import AnalysisJourney from './components/AnalysisJourney.vue'
import { api } from './api'
import { workspaces, type Page, type Role } from './workspaces'
import type { MarketData, ScenarioResult } from './types/api'

const analysisTicker = ref('c2701')
function startAnalysis(ticker: string) { analysisTicker.value = ticker; page.value = 'analysis' }
const page = ref<Page>('overview')
const role = ref<Role>('farmer')
const active = computed(() => workspaces[role.value])
const recordLabels = { farmer: '我的保单', cooperative: '成员台账', insurer: '承保与理赔', authority: '区域项目' }
const overviewActions = { farmer: '查看我的保单', cooperative: '管理成员保障', insurer: '办理承保与理赔', authority: '查看区域项目' }
const tabs = computed(() => role.value === 'insurer' ? [
  { id: 'market' as const, label: '玉米行情' },
  { id: 'analysis' as const, label: '客户风险分析' },
  { id: 'comparison' as const, label: '模型评估' },
  { id: 'overview' as const, label: active.value.overview },
  { id: 'records' as const, label: recordLabels[role.value] },
  { id: 'scenario' as const, label: active.value.scenario },
] : [
  { id: 'overview' as const, label: active.value.overview },
  { id: 'records' as const, label: recordLabels[role.value] },
  { id: 'market' as const, label: '玉米行情' },
  { id: 'scenario' as const, label: active.value.scenario },
])
// Each demo role keeps its own hypothetical inputs; switching is not authentication.
const inputs = ref(Object.fromEntries(Object.entries(workspaces).map(([key, value]) => [key, { ...value.initial }])) as Record<Role, ScenarioInput>)
type ScenarioInput = Parameters<typeof api.scenario>[0]
const form = computed(() => inputs.value[role.value])
const market = ref<MarketData | null>(null)
const loading = ref(true)
const loadError = ref('')
const scenarioError = ref('')
const calculating = ref(false)
const result = ref<ScenarioResult | null>(null)
const stress = ref<{ price: number; payout: number }[]>([])
let requestId = 0
const money = (value?: number) => value == null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
const latest = computed(() => market.value?.series.at(-1))
const validation = computed(() => {
  if (Object.entries(form.value).some(([key, value]) => !(key === 'payout_cap' && value === null) && (typeof value !== 'number' || !Number.isFinite(value) || value < 0))) return '请填写完整的非负数字。'
  if (form.value.insured_tons > 1000000) return '保障数量不能超过 1,000,000 吨。'
  if (form.value.guarantee_price > 100000 || form.value.settlement_price > 100000) return '价格不能超过 100,000 元/吨。'
  return ''
})

function usePolicy(policy: Policy) {
  inputs.value[role.value] = {
    insured_tons: policy.tons, guarantee_price: policy.guarantee,
    settlement_price: policy.status === '已结算' ? policy.settlement : 2450,
    deductible_per_ton: policy.deductible, payout_cap: policy.cap,
  }
  page.value = 'scenario'
}

async function refreshScenario() {
  const id = ++requestId
  result.value = null; stress.value = []; scenarioError.value = ''
  calculating.value = false
  if (validation.value) return
  const body = { ...form.value }
  calculating.value = true
  try {
    const prices = [body.settlement_price, Math.max(body.settlement_price - 100, 0), Math.max(body.settlement_price - 200, 0)]
    const results = await Promise.all(prices.map(settlement_price => api.scenario({ ...body, settlement_price })))
    if (id !== requestId) return
    result.value = results[0]!
    stress.value = results.map((value, index) => ({ price: prices[index]!, payout: value.gross_payout }))
  } catch (e) {
    if (id === requestId) scenarioError.value = e instanceof Error ? e.message : '测算暂不可用，请重试。'
  } finally { if (id === requestId) calculating.value = false }
}
watch(form, refreshScenario, { deep: true })
watch(role, () => { page.value = role.value === 'insurer' ? 'market' : 'overview' })
async function loadMarket() {
  loading.value = true; loadError.value = ''
  try { market.value = await api.market() }
  catch { loadError.value = '行情暂时无法加载，请重试。保障试算仍可单独使用。' }
  finally { loading.value = false }
}
onMounted(() => { void loadMarket(); void refreshScenario() })
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-icon">禾</div><div><strong>GrainGuard</strong><small>玉米价格保障工作台</small></div></div>
      <div class="workspace-label">业务工作台 <span>{{ active.label }}</span></div>
      <nav aria-label="业务导航"><button v-for="item in tabs" :key="item.id" :class="{ active: page === item.id }" :aria-label="item.label" :aria-current="page === item.id ? 'page' : undefined" @click="page = item.id"><span class="nav-dot"></span><span class="nav-label">{{ item.label }}</span></button></nav>
      <div class="sidebar-bottom"><div class="avatar">{{ active.label.slice(0, 1) }}</div><div><strong>{{ active.label }}</strong><small>演示业务视角</small></div></div>
    </aside>
    <main class="main-content">
      <header class="topbar"><div class="breadcrumbs">{{ active.label }} <span>/</span> <b>{{ tabs.find(item => item.id === page)?.label }}</b></div><label class="role-picker">演示角色切换<select v-model="role"><option v-for="(workspace, key) in workspaces" :key="key" :value="key">{{ workspace.label }}</option></select></label></header>
      <section class="page-heading"><div><span class="eyebrow">{{ active.label }} · {{ page === 'market' ? '价格观察' : page === 'scenario' ? '情景试算' : '业务工作台' }}</span><h1>{{ page === 'overview' ? active.title : page === 'records' ? recordLabels[role] : page === 'analysis' ? '客户风险分析' : page === 'market' ? '玉米行情与价格预测' : page === 'comparison' ? '赔付风险评估' : active.scenario }}</h1></div><button v-if="page === 'overview'" class="primary-btn" @click="page = 'records'">{{ overviewActions[role] }} ↗</button></section>
      <template v-if="page === 'scenario'">
        <div v-if="loadError" class="error-banner" role="alert">{{ loadError }} <button class="text-btn" @click="loadMarket">重新加载行情</button></div>
        <div v-else-if="loading" class="source-banner" role="status">正在加载行情…</div>
        <div v-else-if="market" class="source-banner" :class="{ 'source-live': ['uqer', 'parquet'].includes(market.provider) }"><span class="source-icon">i</span><div><strong>{{ ['uqer', 'parquet'].includes(market.provider) ? '真实期货历史快照 · 仅供价格观察' : '模拟行情 · 不代表真实市场价格' }}</strong><small>{{ market.warning }}</small><small>历史快照不代表实时行情；期货价格不能直接作为保单结算价。</small></div><span class="source-date">样本截至 {{ latest?.date }}</span></div>
      </template>
      <div v-if="page === 'scenario'" class="scenario-context"><span class="pill-soft">假设情景 · 非真实保单</span><span>保障价 {{ money(form.guarantee_price) }} / 情景价 {{ money(form.settlement_price) }} 元/吨</span></div>
      <div v-if="page === 'scenario' && (validation || scenarioError)" class="error-banner" role="alert">{{ validation || scenarioError }} <button v-if="scenarioError" class="text-btn" @click="refreshScenario">重试测算</button></div>
      <div v-if="page === 'scenario' && calculating" class="calculation-status" role="status">正在更新情景测算…</div>

      <BusinessWorkspace v-if="page === 'overview' || page === 'records'" :role="role" :records="page === 'records'" @navigate="page = 'records'" @scenario="usePolicy" @comparison="page = 'comparison'" />

      <ModelComparisonWorkspace v-else-if="page === 'comparison'" @scenario="page = 'scenario'" />

      <MarketWorkspace v-else-if="page === 'market'" :insurer="role === 'insurer'" @analyze="startAnalysis" />

      <template v-else-if="page === 'scenario'">
        <div class="scenario-layout"><section class="panel input-panel"><div class="panel-heading"><h2>保障与价格假设</h2></div>
          <label class="field"><span>{{ active.quantity }} <small>吨</small></span><input v-model.number="form.insured_tons" type="number" min="0" max="1000000" step="1" /></label>
          <label class="field"><span>保障目标价 <small>元/吨</small></span><input v-model.number="form.guarantee_price" type="number" min="0" max="100000" step="10" /></label>
          <label class="field"><span>情景结算价 <small>元/吨</small></span><input v-model.number="form.settlement_price" type="number" min="0" max="100000" step="10" /></label>
          <label class="field"><span>每吨免赔额 <small>元/吨</small></span><input v-model.number="form.deductible_per_ton" type="number" min="0" step="10" /></label>
          <label class="field"><span>赔付上限 <small>元，留空不封顶</small></span><input :value="form.payout_cap ?? ''" type="number" min="0" step="1000" @input="form.payout_cap = ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value)" /></label>
          <p class="business-note">上限留空不封顶；0元表示不赔付。</p>
        </section><section class="panel result-panel" aria-live="polite"><div class="result-top"><h2>{{ !result ? '等待有效测算' : result.triggered ? '本情景触发赔付' : '本情景无赔付' }}</h2><span class="pill-soft">假设情景</span></div><div class="payout-number">¥ {{ money(result?.gross_payout) }}</div><div class="payout-caption">{{ active.label }} · 情景赔付金额</div><dl class="business-list"><div><dt>限额前每吨价差赔付</dt><dd>{{ money(result?.loss_per_ton) }} 元/吨</dd></div><div><dt>{{ active.quantity }}</dt><dd>{{ money(result?.insured_tons) }} 吨</dd></div><div><dt>应用上限后的实际每吨赔付</dt><dd>{{ money(result && result.insured_tons > 0 ? result.gross_payout / result.insured_tons : undefined) }} 元/吨</dd></div></dl><details class="calculation-details"><summary>查看赔付计算口径</summary><p>保障价减情景结算价，再减每吨免赔额；正差额乘保障数量，最终金额不超过赔付上限。</p></details></section></div>
        <section class="panel records-panel"><div class="panel-heading"><h2>价格下跌情景对比</h2></div><table class="scenario-table"><thead><tr><th>情景结算价（元/吨）</th><th>赔付金额（元）</th></tr></thead><tbody><tr v-for="(row,index) in stress" :key="index"><td>{{ money(row.price) }}</td><td>{{ money(row.payout) }}</td></tr></tbody></table></section>
        <div class="disclaimer">当前为假设情景，不代表真实保单或实际理赔。实际赔付以合同约定的价格来源、保障期限和条款为准。</div>
      </template>
      <AnalysisJourney v-if="role === 'insurer'" v-show="page === 'analysis'" :ticker="analysisTicker" @market="page = 'market'" @comparison="page = 'comparison'" />
      <footer>GRAINGUARD <span>保险 + 期货 · 价格保障情景演示</span></footer>
    </main>
  </div>
</template>
