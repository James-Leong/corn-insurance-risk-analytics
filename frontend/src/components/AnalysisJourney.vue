<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { AnalysisInput, AnalysisOptions, AnalysisReport, UnderwritingDecision, UnderwritingPlan, UnderwritingTrial } from '../types/analysis'
const props = defineProps<{ ticker?: string }>()
const emit = defineEmits<{ market: []; comparison: [] }>()
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T
const options = ref<AnalysisOptions | null>(null)
const form = ref<AnalysisInput | null>(null)
const report = ref<AnalysisReport | null>(null)
const loading = ref(false), error = ref(''), step = ref(1), stale = ref(false)
const stages = ['研究合同', '风险与压力', '业务判断', '承保方案', '赔付试算', '分析报告']
const decisionForm = ref<{ method_id: string; outcome: UnderwritingDecision['outcome']; limit: number | null; reason: string }>({ method_id: '', outcome: 'accept', limit: null, reason: '' })
const decision = ref<UnderwritingDecision | null>(null)
const planForm = ref<{ deductible: number; cap: number | null }>({ deductible: 0, cap: null })
const plan = ref<UnderwritingPlan | null>(null)
const trialSource = ref<UnderwritingTrial['price_source']>('historical')
const trialPrice = ref<number>(0)
const trial = ref<UnderwritingTrial | null>(null)
const trialLoading = ref(false), trialError = ref('')
let requestId = 0, trialRequestId = 0
const money = (v: number | null | undefined) => v == null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(v)
const percent = (v: number | null | undefined) => v == null ? '—' : `${(v * 100).toFixed(1)}%`
const nonnegative = (v: unknown, max = 1e10): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= max
function nullableNumber(event: Event) { const value = (event.target as HTMLInputElement).value; return value === '' ? null : Number(value) }
const dates = computed(() => options.value?.contracts.find(c => c.ticker === form.value?.ticker)?.valuation_dates ?? [])
const valid = computed(() => form.value && nonnegative(form.value.quantity, 100000) && form.value.quantity > 0 && nonnegative(form.value.budget) && nonnegative(form.value.deductible, 10000) && (form.value.payout_cap === null || nonnegative(form.value.payout_cap)))
const current = computed(() => !!report.value && !stale.value && !loading.value)
const selectedMethod = computed(() => report.value?.methods.find(m => m.method_id === decisionForm.value.method_id))
const decisionValid = computed(() => current.value && selectedMethod.value && nonnegative(selectedMethod.value.expected_payout) && decisionForm.value.reason.trim().length > 0 && (decisionForm.value.limit === null || nonnegative(decisionForm.value.limit)))
const overLimit = computed(() => selectedMethod.value?.expected_payout != null && decisionForm.value.limit !== null && selectedMethod.value.expected_payout > decisionForm.value.limit)
const canConfirmDecision = computed(() => decisionValid.value && (decisionForm.value.outcome !== 'accept' || !overLimit.value))
const planValid = computed(() => nonnegative(planForm.value.deductible, 10000) && (planForm.value.cap === null || nonnegative(planForm.value.cap)))
const modelScopeMatches = computed(() => planForm.value.deductible === 0 && planForm.value.cap === null)
const trialValid = computed(() => !!plan.value && current.value && nonnegative(trialPrice.value, 100000))
const canExport = computed(() => current.value && !!decision.value && (decision.value.outcome !== 'accept' || (!!plan.value && !!trial.value && !trialLoading.value)))
const outcomes = { accept: '风险可接受', adjust: '调整承保条件', decline: '暂不承保' }
function invalidateTrial() { trialRequestId++; trial.value = null; trialLoading.value = false; trialError.value = '' }
function invalidatePlan() { plan.value = null; invalidateTrial() }
function invalidateDecision() { decision.value = null; invalidatePlan() }
watch(form, () => { if (report.value) stale.value = true; requestId++; loading.value = false; invalidateDecision() }, { deep: true, flush: 'sync' })
watch(() => form.value?.ticker, () => { if (form.value && !dates.value.includes(form.value.valuation_date)) form.value.valuation_date = dates.value.at(-1) ?? '' }, { flush: 'sync' })
watch(decisionForm, invalidateDecision, { deep: true, flush: 'sync' })
watch(planForm, invalidatePlan, { deep: true, flush: 'sync' })
watch(trialPrice, invalidateTrial, { flush: 'sync' })
watch(trialSource, value => { invalidateTrial(); if (value === 'historical' && report.value) trialPrice.value = report.value.observed.mean_settlement }, { flush: 'sync' })
watch(() => props.ticker, () => { if (options.value) preset(false) })
async function load() {
  loading.value = true; error.value = ''
  try { const r = await fetch('/api/v1/analysis/options'); if (!r.ok) throw new Error('历史分析选项暂不可用，请重试。'); options.value = await r.json(); preset(false) }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}
function preset(run = true) {
  if (!options.value) return
  form.value = clone(options.value.defaults)
  if (props.ticker && options.value.contracts.some(c => c.ticker === props.ticker)) form.value.ticker = props.ticker
  if (!dates.value.includes(form.value.valuation_date)) form.value.valuation_date = dates.value.at(-1) ?? ''
  decisionForm.value = { method_id: '', outcome: 'accept', limit: null, reason: '' }
  planForm.value = { deductible: 0, cap: null }; step.value = 1
  if (run) void calculate()
}
async function calculate() {
  if (!valid.value || !form.value) return
  const id = ++requestId; loading.value = true; error.value = ''; stale.value = true; invalidateDecision()
  try {
    const r = await fetch('/api/v1/analysis/estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form.value) })
    const body = await r.json()
    if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message ?? `分析失败 (${r.status})`)
    if (id !== requestId) return
    report.value = body; stale.value = false; step.value = 2
  } catch (e) { if (id === requestId) error.value = e instanceof Error ? e.message : '分析暂不可用。' }
  finally { if (id === requestId) loading.value = false }
}
function confirmDecision() {
  if (!canConfirmDecision.value || !selectedMethod.value || !report.value) return
  decision.value = { outcome: decisionForm.value.outcome, method_id: selectedMethod.value.method_id, method_name: selectedMethod.value.name, expected_payout: selectedMethod.value.expected_payout!, expected_payout_limit: decisionForm.value.limit, reason: decisionForm.value.reason.trim(), source_report_id: report.value.report_id }
  invalidatePlan()
}
function confirmPlan() {
  if (!current.value || !report.value || decision.value?.outcome !== 'accept' || !planValid.value) return
  plan.value = { source_report_id: report.value.report_id, contract: clone(report.value.contract), price_rule: '观察期20个交易日结算价算术均值', deductible_per_ton: planForm.value.deductible, payout_cap: planForm.value.cap, budget: report.value.request.budget, model_scope: modelScopeMatches.value ? 'matched' : 'base_terms_only', decision: clone(decision.value) }
  trialSource.value = 'historical'; trialPrice.value = report.value.observed.mean_settlement
  invalidateTrial(); step.value = 5
}
async function calculateTrial() {
  if (!trialValid.value || !plan.value) return
  const id = ++trialRequestId, snapshot = clone(plan.value), price = trialPrice.value, source = trialSource.value
  trial.value = null; trialError.value = ''; trialLoading.value = true
  try {
    const value = await api.scenario({ insured_tons: snapshot.contract.quantity, guarantee_price: snapshot.contract.guarantee_price, settlement_price: price, deductible_per_ton: snapshot.deductible_per_ton, payout_cap: snapshot.payout_cap })
    if (id !== trialRequestId) return
    trial.value = { price_source: source, settlement_price: price, payout: value.gross_payout, budget_gap: Math.max(Math.round((value.gross_payout - snapshot.budget) * 100) / 100, 0) }
  } catch (e) { if (id === trialRequestId) trialError.value = e instanceof Error ? e.message : '试算失败，请重试。' }
  finally { if (id === trialRequestId) trialLoading.value = false }
}
function canGo(stage: number) {
  if (stage === 1) return true
  if (!current.value) return false
  if (stage <= 3) return true
  if (stage === 4) return decision.value?.outcome === 'accept'
  if (stage === 5) return !!plan.value
  return canExport.value
}
function download() {
  if (!canExport.value || !report.value) return
  const payload = { ...clone(report.value), underwriting_schema_version: 'underwriting-v1', underwriting: { decision: clone(decision.value), plan: clone(plan.value), trial: clone(trial.value) } }
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = `${report.value.report_id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function print() { if (canExport.value) window.print() }
onMounted(load)
</script>
<template>
  <div class="analysis-journey">
    <div class="source-banner source-live"><strong>历史回放 · 玉米价格险研究</strong><button class="select-btn" @click="emit('market')">返回玉米行情</button></div>
    <div class="journey-steps no-print"><button v-for="(label, i) in stages" :key="label" :class="{ active: step === i + 1 }" :disabled="!canGo(i + 1)" @click="step = i + 1">{{ i + 1 }} · {{ label }}</button></div>
    <div v-if="error" class="error-banner" role="alert">{{ error }} <button class="text-btn" @click="options ? calculate() : load()">重试</button></div>
    <p v-if="loading" role="status">正在读取离线数据并计算…</p>
    <template v-if="form && options">
      <section v-if="step === 1" class="panel no-print">
        <div class="panel-heading"><h2>选择研究合同</h2><button class="select-btn" :disabled="loading" @click="preset()">使用演示案例并分析</button></div>
        <div class="journey-fields">
          <label>玉米合约<select v-model="form.ticker"><option v-for="c in options.contracts" :key="c.ticker" :value="c.ticker">{{ c.ticker.toUpperCase() }}</option></select></label>
          <label>历史估值日<select v-model="form.valuation_date"><option v-for="d in dates" :key="d">{{ d }}</option></select></label>
          <label>保障价比例<select v-model.number="form.strike_ratio"><option v-for="r in options.strike_ratios" :key="r" :value="r">{{ (r * 100).toFixed(0) }}%</option></select></label>
          <label>保障数量（吨）<input v-model.number="form.quantity" type="number" min="1" max="100000" /></label>
          <label>资金预算（元）<input v-model.number="form.budget" type="number" min="0" max="10000000000" /></label>
        </div>
        <p class="business-note">模型条款 · 20交易日均价 · 零免赔 · 不封顶</p>
        <p v-if="!valid" class="error-banner" role="alert">请填写有效数量和预算；数量大于0且不超过100,000吨。</p>
        <button class="primary-btn" :disabled="!valid || loading" @click="calculate">计算赔付风险 →</button>
      </section>
      <p v-if="stale && report" class="disclaimer" role="status">分析条件已修改，请重新计算并确认业务判断。</p>
      <template v-if="report && !stale">
        <div class="journey-context">{{ report.contract.ticker.toUpperCase() }} · 估值 {{ report.contract.valuation_date }} · 保障价 {{ money(report.contract.guarantee_price) }} 元/吨 · {{ money(report.contract.quantity) }} 吨</div>
        <section v-if="step === 6" class="panel journey-result printable-report">
          <h2>客户分析报告</h2>
          <dl class="comparison-details"><div><dt>观察期</dt><dd>{{ report.contract.observation_start }} — {{ report.contract.observation_end }}</dd></div><div><dt>采价规则</dt><dd>20交易日结算价算术均值</dd></div><div><dt>估值日结算价</dt><dd>{{ money(report.price_references.last) }} 元/吨</dd></div><div><dt>估值日前20日均价</dt><dd>{{ money(report.price_references.ma20) }} 元/吨</dd></div></dl>
        </section>
        <section v-if="step === 2 || step === 6" class="panel journey-result">
          <h2>估值时点的赔付风险</h2><p class="business-note">零免赔、不封顶 · 研究估计 · P90未发布</p>
          <div class="table-scroll"><table class="business-table"><thead><tr><th>方法</th><th>触发概率</th><th>触发后平均赔款（元）</th><th>预期赔款（元）</th></tr></thead><tbody><tr v-for="m in report.methods" :key="m.method_id"><td>{{ m.name }}</td><td>{{ percent(m.claim_probability) }}</td><td>{{ money(m.conditional_mean_payout) }}</td><td>{{ money(m.expected_payout) }}</td></tr></tbody></table></div>
          <details class="calculation-details no-print"><summary>事后观察结果</summary><p>观察期 {{ report.contract.observation_start }} 至 {{ report.contract.observation_end }}；实际均价 {{ money(report.observed.mean_settlement) }} 元/吨；基础条款规则赔款 {{ money(report.observed.payout) }} 元。</p></details>
          <button v-if="step === 2" class="text-btn" @click="emit('comparison')">查看完整模型验证证据 ↗</button>
        </section>
        <section v-if="step === 2 || step === 6" class="panel journey-result">
          <h2>基础条款压力情景</h2><p class="business-note">资金预算 {{ money(report.request.budget) }} 元</p>
          <div class="table-scroll"><table class="business-table"><thead><tr><th>价格变化</th><th>情景价（元/吨）</th><th>赔款（元）</th><th>预算缺口（元）</th></tr></thead><tbody><tr v-for="s in report.stress" :key="s.shock_percent"><td>{{ s.shock_percent > 0 ? '+' : '' }}{{ s.shock_percent }}%</td><td>{{ money(s.scenario_price) }}</td><td>{{ money(s.gross_payout) }}</td><td :class="{ negative: s.budget_gap > 0 }">{{ money(s.budget_gap) }}</td></tr></tbody></table></div>
        </section>
        <section v-if="step === 3" class="panel no-print">
          <h2>业务承保判断</h2>
          <div class="journey-fields">
            <label>本方案参考方法<select v-model="decisionForm.method_id" aria-label="本方案参考方法"><option value="">请选择</option><option v-for="m in report.methods" :key="m.method_id" :value="m.method_id" :disabled="m.expected_payout == null">{{ m.name }}</option></select></label>
            <label>可接受预期赔款上限（元，选填）<input :value="decisionForm.limit ?? ''" type="number" min="0" max="10000000000" @input="decisionForm.limit = nullableNumber($event)" /></label>
            <label>承保意见<select v-model="decisionForm.outcome" aria-label="承保意见"><option value="accept">风险可接受</option><option value="adjust">调整承保条件</option><option value="decline">暂不承保</option></select></label>
            <div v-if="selectedMethod" class="decision-reference"><span>参考预期赔款</span><strong>{{ money(selectedMethod.expected_payout) }} 元</strong><span>触发概率 {{ percent(selectedMethod.claim_probability) }}</span></div>
          </div>
          <label class="decision-reason">判断依据<textarea v-model="decisionForm.reason" maxlength="1000" rows="3" /></label>
          <p v-if="overLimit" class="error-banner" role="status">参考预期赔款超出所设限额。请调整条件或限额后再接受风险。</p>
          <button class="primary-btn" :disabled="!canConfirmDecision" @click="confirmDecision">确认业务判断</button>
          <div v-if="decision" class="decision-confirmed"><strong>{{ outcomes[decision.outcome] }}</strong><p>{{ decision.reason }}</p></div>
        </section>
        <section v-if="step === 4 && decision?.outcome === 'accept'" class="panel no-print">
          <h2>承保方案要点</h2>
          <dl class="comparison-details"><div><dt>标的合约</dt><dd>{{ report.contract.ticker.toUpperCase() }}</dd></div><div><dt>采价观察期</dt><dd>{{ report.contract.observation_start }} — {{ report.contract.observation_end }}</dd></div><div><dt>采价规则</dt><dd>20交易日结算价算术均值</dd></div><div><dt>保障价 / 数量</dt><dd>{{ money(report.contract.guarantee_price) }} 元/吨 · {{ money(report.contract.quantity) }} 吨</dd></div><div><dt>参考方法</dt><dd>{{ decision.method_name }}</dd></div><div><dt>基础条款预期赔款</dt><dd>{{ money(decision.expected_payout) }} 元</dd></div></dl>
          <div class="journey-fields"><label>方案每吨免赔（元/吨）<input v-model.number="planForm.deductible" type="number" min="0" max="10000" /></label><label>方案赔付上限（元，留空不封顶）<input :value="planForm.cap ?? ''" type="number" min="0" max="10000000000" @input="planForm.cap = nullableNumber($event)" /></label></div>
          <p v-if="!modelScopeMatches" class="disclaimer">附加条款仅作规则试算；模型风险参考仍对应零免赔、不封顶。</p>
          <div class="detail-buttons"><button class="primary-btn" :disabled="!planValid" @click="confirmPlan">确认方案并带入试算 →</button><button class="select-btn" @click="step = 1">调整保障价或数量</button></div>
        </section>
        <section v-if="step === 5 && plan" class="panel no-print">
          <h2>按承保方案试算</h2>
          <p class="business-note">{{ plan.contract.ticker.toUpperCase() }} · 保障价 {{ money(plan.contract.guarantee_price) }} 元/吨 · {{ money(plan.contract.quantity) }} 吨 · 免赔 {{ money(plan.deductible_per_ton) }} 元/吨 · 上限 {{ plan.payout_cap === null ? '不封顶' : `${money(plan.payout_cap)} 元` }}</p>
          <div class="journey-fields"><label>结算价格来源<select v-model="trialSource" aria-label="结算价格来源"><option value="historical">历史观察均价</option><option value="scenario">自定义价格情景</option></select></label><label>试算均价（元/吨）<input v-model.number="trialPrice" type="number" min="0" max="100000" step="0.01" :disabled="trialSource === 'historical'" /></label></div>
          <div v-if="trialError" class="error-banner" role="alert">{{ trialError }}</div>
          <button class="primary-btn" :disabled="!trialValid || trialLoading" @click="calculateTrial">{{ trialLoading ? '正在试算…' : '计算方案赔款' }}</button>
          <div v-if="trial" class="plan-trial-result"><div><span>方案规则赔款</span><strong>{{ money(trial.payout) }} 元</strong></div><div><span>资金预算</span><strong>{{ money(plan.budget) }} 元</strong></div><div><span>预算缺口</span><strong>{{ money(trial.budget_gap) }} 元</strong></div></div>
        </section>
        <template v-if="step === 6 && decision">
          <section class="panel journey-result printable-report"><h2>业务判断与承保方案</h2><dl class="comparison-details"><div><dt>承保意见</dt><dd>{{ outcomes[decision.outcome] }}</dd></div><div><dt>参考方法</dt><dd>{{ decision.method_name }}</dd></div><div><dt>可接受预期赔款上限</dt><dd>{{ decision.expected_payout_limit === null ? '未设置' : `${money(decision.expected_payout_limit)} 元` }}</dd></div><div><dt>判断依据</dt><dd>{{ decision.reason }}</dd></div></dl><template v-if="plan"><dl class="comparison-details"><div><dt>保障价 / 数量</dt><dd>{{ money(plan.contract.guarantee_price) }} 元/吨 · {{ money(plan.contract.quantity) }} 吨</dd></div><div><dt>每吨免赔 / 赔付上限</dt><dd>{{ money(plan.deductible_per_ton) }} 元/吨 · {{ plan.payout_cap === null ? '不封顶' : `${money(plan.payout_cap)} 元` }}</dd></div></dl><p v-if="plan.model_scope === 'base_terms_only'" class="business-note">方案附加条款仅作规则试算；模型估计对应基础条款。</p></template></section>
          <section v-if="trial && plan" class="panel journey-result printable-report"><h2>方案赔付试算结果</h2><dl class="comparison-details"><div><dt>价格来源</dt><dd>{{ trial.price_source === 'historical' ? '历史观察均价' : '自定义价格情景' }}</dd></div><div><dt>试算均价</dt><dd>{{ money(trial.settlement_price) }} 元/吨</dd></div><div><dt>方案规则赔款</dt><dd>{{ money(trial.payout) }} 元</dd></div><div><dt>预算缺口</dt><dd>{{ money(trial.budget_gap) }} 元</dd></div></dl></section>
          <section class="panel journey-result printable-report"><h2>事后核对</h2><dl class="comparison-details"><div><dt>观察期实际均价</dt><dd>{{ money(report.observed.mean_settlement) }} 元/吨</dd></div><div><dt>基础研究条款赔款</dt><dd>{{ money(report.observed.payout) }} 元</dd></div></dl><p class="business-note">历史研究参考；正式承保和核赔须按产品条款及业务审核执行。</p><details class="calculation-details technical-trace no-print"><summary>技术追溯</summary><dl class="comparison-details"><div><dt>报告标识</dt><dd>{{ report.report_id }}</dd></div><div><dt>数据校验值</dt><dd>{{ report.versions.data }}</dd></div><div><dt>模型版本</dt><dd>{{ report.versions.model }}</dd></div><div><dt>规则版本</dt><dd>{{ report.versions.rule }}</dd></div><div><dt>研究运行</dt><dd>{{ report.run_id }}</dd></div></dl></details><div class="detail-buttons no-print"><button class="primary-btn" :disabled="!canExport" @click="print">打印 / 保存 PDF</button><button class="select-btn" :disabled="!canExport" @click="download">下载分析 JSON</button></div></section>
        </template>
      </template>
      <div class="journey-navigation no-print">
        <button v-if="step > 1" class="select-btn" @click="step = step === 6 && !plan ? 3 : step - 1">← 上一步</button>
        <button v-if="step === 2" class="primary-btn" :disabled="!current" @click="step = 3">继续：业务判断 →</button>
        <button v-if="step === 3 && decision?.outcome === 'accept'" class="primary-btn" @click="step = 4">制定承保方案 →</button>
        <button v-if="step === 3 && decision?.outcome === 'adjust'" class="primary-btn" @click="step = 1">调整条件并重新分析 →</button>
        <button v-if="step === 3 && decision?.outcome === 'decline'" class="primary-btn" @click="step = 6">生成判断报告 →</button>
        <button v-if="step === 5" class="primary-btn" :disabled="!canExport" @click="step = 6">生成分析报告 →</button>
        <button v-if="step === 6" class="select-btn" @click="step = 1">调整研究合同</button>
      </div>
    </template>
  </div>
</template>
