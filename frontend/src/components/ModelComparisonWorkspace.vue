<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { comparisonApi } from '../api'
import ComparisonCalibration from './ComparisonCalibration.vue'
import ComparisonDataQuality from './ComparisonDataQuality.vue'
import type { ComparisonCase, ComparisonGroup, ComparisonMetrics, ComparisonRun, Evidence, Partition } from '../types/comparison'
const emit = defineEmits<{ scenario: [] }>()
const tab = ref('risk')
const groups = ref<ComparisonGroup[]>([]), runs = ref<ComparisonRun[]>([])
const groupId = ref(''), runId = ref(''), caseId = ref(''), partition = ref<Partition>('validation')
const report = ref<ComparisonRun | null>(null), metrics = ref<ComparisonMetrics | null>(null)
const cases = ref<ComparisonCase[]>([]), evidence = ref<Evidence[]>([])
const loading = ref(false), error = ref(''), exportError = ref(''), exporting = ref(false)
let sequence = 0
const names: Record<string, string> = { historical_blocks: '历史收益分块重采样', glm_hurdle: 'Logistic＋Gamma', xgboost_hurdle: '两阶段 XGBoost', price_last: '最近结算价', price_ma20: '20日移动均价' }
const labels: Record<string, string> = { limited_history_research_only: '历史跨度有限，暂不指定正式采用方法',  trigger_brier: 'Brier 概率误差', method_unavailable: '方法暂不可用', price_rmse: '价格 RMSE', price_mean_rmse: '均价 RMSE', method_id: '方法', bin_lower: '概率区间下限', bin_upper: '概率区间上限', predicted_probability: '平均预测概率', observed_frequency: '实际触发频率', sample_count: '样本数', date_count: '独立日期数', group: '分组', rmse: 'RMSE', bias: '均值偏差', unit: '单位', data_version: '行情快照版本', rule_version: '条款版本', split_version: '样本划分版本', sample_hash: '目标样本摘要', window_trading_days: '观察窗交易日数', task: '研究任务',  research_only: '研究对照', eligible_for_pilot: '具备试点资格', rejected: '未通过', not_evaluated: '尚未评估', insufficient_data: '样本不足', not_validated: '尚未通过独立验证', unsupported: '不支持 P90', validated: '已验证', no_measured_result: '尚无实测结果', completed: '计算完成', incomplete: '部分完成', failed: '计算失败', rule_generated: '合同规则生成标签', authorized_claim: '授权核定赔案标签', calibration: '概率可靠性', error_slices: '分组误差', data_quality: '数据质量', expected_payout_rmse: '预期赔款 RMSE', expected_payout_mae: '预期赔款 MAE', expected_payout_bias: '预期赔款偏差', brier: 'Brier 概率误差' }
const label = (value?: string | null) => value ? labels[value] || value : '—'
const number = (value?: number | null) => value == null || !Number.isFinite(value) ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
const unit = (value: string) => ({ CNY: '元', 'CNY/ton': '元/吨', probability_squared: '', probability: '' }[value] ?? value)
const percent = (value?: number | null) => value == null ? '—' : `${number(value * 100)}%`
const activeCase = computed(() => cases.value.find(item => item.case_id === caseId.value))
const riskOutputs = computed(() => activeCase.value?.outputs.filter(item => !item.method_id.startsWith('price_')) || [])
const priceOutputs = computed(() => activeCase.value?.outputs.filter(item => item.method_id.startsWith('price_')) || [])
const selectedOutput = computed(() => riskOutputs.value.find(item => item.method_id === report.value?.selection.selected_method_id))
const metricModels = computed(() => metrics.value?.models.filter(item => item.task !== 'price_reference' && !item.method_id.startsWith('price_')) || [])
const metricIds = computed(() => [...new Set(metricModels.value.flatMap(item => item.metrics.map(metric => metric.metric_id)))])
function clearReport() { report.value = null; metrics.value = null; cases.value = []; evidence.value = []; caseId.value = ''; exportError.value = '' }
async function loadAll() {
  const id = ++sequence; loading.value = true; error.value = ''; clearReport(); groups.value = []; runs.value = []
  try {
    const result = await comparisonApi.groups()
    if (id !== sequence) return
    groups.value = result.items; groupId.value = result.default_group_id || result.items[0]?.comparison_group_id || ''
    if (groupId.value) await loadGroup()
  } catch (e) { if (id === sequence) error.value = e instanceof Error ? e.message : '无法连接研究报告服务' }
  finally { if (id === sequence) loading.value = false }
}
async function loadGroup() {
  const id = ++sequence; loading.value = true; error.value = ''; clearReport(); runs.value = []; runId.value = ''; partition.value = 'validation'
  try {
    const result = await comparisonApi.runs(groupId.value)
    if (id !== sequence) return
    runs.value = result.items; runId.value = result.items[0]?.run_id || ''
    if (runId.value) await loadRun()
  } catch (e) { if (id === sequence) error.value = e instanceof Error ? e.message : '批次读取失败' }
  finally { if (id === sequence) loading.value = false }
}
async function loadRun(resetPartition = false) {
  if (resetPartition) partition.value = 'validation'
  const id = ++sequence; loading.value = true; error.value = ''; clearReport()
  const currentRun = runId.value, currentPartition = partition.value
  try {
    const [metadata, scores, examples, charts] = await Promise.all([
      comparisonApi.run(currentRun, currentPartition), comparisonApi.metrics(currentRun, currentPartition), comparisonApi.cases(currentRun, currentPartition),
      Promise.all(['calibration', 'error_slices', 'data_quality'].map(view => comparisonApi.evidence(currentRun, currentPartition, view))),
    ])
    if (id !== sequence) return
    report.value = metadata; metrics.value = scores; cases.value = examples.items; evidence.value = charts; caseId.value = examples.items[0]?.case_id || ''
  } catch (e) { if (id === sequence) error.value = e instanceof Error ? e.message : '报告读取失败' }
  finally { if (id === sequence) loading.value = false }
}
async function download(format: 'json' | 'csv') {
  exporting.value = true; exportError.value = ''
  try {
    const response = await fetch(comparisonApi.exportUrl(runId.value, partition.value, format))
    if (!response.ok) throw new Error(`导出失败 (${response.status})，请重试`)
    const url = URL.createObjectURL(await response.blob()), anchor = document.createElement('a')
    anchor.href = url; anchor.download = `${runId.value}-${partition.value}.${format}`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { exportError.value = e instanceof Error ? e.message : '导出失败' }
  finally { exporting.value = false }
}
const cell = (value: unknown) => value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : typeof value === 'number' ? number(value) : names[String(value)] || label(String(value))
onMounted(loadAll)
onUnmounted(() => { sequence++ })
</script>

<template>
  <div class="comparison-workspace">
    <div class="comparison-intro"><span class="pill-soft">历史研究 · 只读回放</span><button class="select-btn" @click="emit('scenario')">打开确定性情景试算</button></div>
    <div v-if="groups.length" class="business-toolbar">
      <label>比较组<select v-model="groupId" @change="loadGroup"><option v-for="item in groups" :key="item.comparison_group_id" :value="item.comparison_group_id">{{ item.title }}</option></select></label>
      <label v-if="runs.length">报告批次<select v-model="runId" @change="loadRun(true)"><option v-for="item in runs" :key="item.run_id" :value="item.run_id">{{ item.title }} · {{ item.run_id }}</option></select></label>
      <label v-if="report">评估分区<select v-model="partition" @change="loadRun()"><option v-for="item in report.released_partitions" :key="item" :value="item">{{ item === 'validation' ? '验证集' : '冻结测试集' }}</option></select></label>
    </div>
    <p v-if="loading" class="panel" role="status">正在读取已保存的研究结果…</p>
    <div v-else-if="error" class="error-banner" role="alert">{{ error }} <button class="text-btn" @click="loadAll">重试加载报告</button></div>
    <section v-else-if="!report" class="panel comparison-empty"><h2>尚无可比较的实测结果</h2><p>暂无已发布研究报告。</p><button class="select-btn" @click="loadAll">刷新报告</button></section>
    <template v-else>
      <section class="source-banner" :class="{ 'source-live': report.source_kind === 'measured' }"><div><strong>{{ report.source_kind === 'measured' ? '真实行情研究结果' : '界面联调示例 · 非实测成绩' }} · {{ label(report.run_status) }}</strong><small>{{ label(report.label_kind) }} · 数据范围 {{ report.data_start }} — {{ report.data_end }} · {{ report.protocol.window_trading_days }} 个交易日观察窗</small></div></section>
      <details v-if="report.warnings.length" class="disclaimer comparison-limitations"><summary>研究口径与使用限制{{ report.released_partitions.includes('test') ? '' : ' · 最终测试未发布' }}</summary><ul><li v-for="warning in report.warnings" :key="warning">{{ warning }}</li></ul></details>
      <div class="comparison-tabs" role="tablist" aria-label="风险评估视图"><button v-for="item in [{id:'risk',name:'合同风险'},{id:'methods',name:'方法对照'},{id:'report',name:'验证报告'}]" :id="`comparison-tab-${item.id}`" :key="item.id" role="tab" :aria-selected="tab === item.id" :aria-controls="`comparison-panel-${item.id}`" :class="{active: tab === item.id}" @click="tab = item.id">{{ item.name }}</button></div>
      <section :id="`comparison-panel-${tab}`" role="tabpanel" :aria-labelledby="`comparison-tab-${tab}`">
        <template v-if="tab !== 'report'">
          <label v-if="cases.length" class="comparison-case-picker">固定研究合同<select v-model="caseId"><option v-for="item in cases" :key="item.case_id" :value="item.case_id">{{ item.contract_id }} · {{ item.valuation_date }} · {{ item.case_id }}</option></select></label>
          <p v-else class="panel">当前分区没有可公开的历史个案，请查看验证报告中的样本与失败原因。</p>
          <template v-if="activeCase">
            <section class="panel"><h2>比较条件</h2><dl class="comparison-details"><div><dt>具体期货合约</dt><dd>{{ activeCase.contract_id }}</dd></div><div><dt>历史估值日</dt><dd>{{ activeCase.valuation_date }}</dd></div><div><dt>保障价 / 数量</dt><dd>{{ number(activeCase.guarantee_price) }} 元/吨 · {{ number(activeCase.quantity_tons) }} 吨</dd></div><div><dt>采价字段</dt><dd>{{ activeCase.price_field || '详见规则协议' }}</dd></div><div><dt>免赔 / 上限</dt><dd>{{ number(activeCase.deductible_per_ton) }} 元/吨 · {{ activeCase.payout_cap === null ? '无封顶' : `${number(activeCase.payout_cap)} 元` }}</dd></div><div><dt>规则版本</dt><dd>{{ report.protocol.rule_version }}</dd></div></dl><details v-if="activeCase.observation_dates?.length"><summary>完整观察日（{{ activeCase.observation_dates.length }} 日）</summary><p class="business-note">{{ activeCase.observation_dates.join('、') }}</p></details></section>
            <template v-if="tab === 'risk'">
              <div v-if="selectedOutput" class="comparison-risk-cards"><article class="panel"><small>触发概率</small><strong>{{ percent(selectedOutput.claim_probability) }}</strong></article><article class="panel"><small>触发后平均赔款（元）</small><strong>{{ number(selectedOutput.conditional_mean_payout) }}</strong></article><article class="panel"><small>预期赔款（元）</small><strong>{{ number(selectedOutput.expected_payout) }}</strong></article></div>
              <section v-else class="panel comparison-empty"><h2>尚未指定可采用方法</h2><p>{{ label(report.selection.reason_code) }}</p></section>
              <p v-if="selectedOutput" class="business-note">采用方法：{{ names[selectedOutput.method_id] || selectedOutput.method_id }}。P90：{{ selectedOutput.p90_status === 'validated' ? `${number(selectedOutput.p90_payout)} 元` : label(selectedOutput.p90_status) }}。条件均额仅针对发生赔付的情景。</p>
              <button class="text-btn" @click="tab = 'methods'">查看全部方法对照 →</button>
              <section class="panel comparison-observed"><h2>事后验证</h2><p>观察期规则赔款 <strong>{{ number(activeCase.observed_payout) }} 元</strong></p></section>
            </template>
            <template v-else>
              <div class="table-scroll panel"><table class="business-table comparison-table"><thead><tr><th>方法</th><th>触发概率</th><th>条件均额（元）</th><th>预期赔款（元）</th><th>P90（元）</th><th>状态 / 原因</th></tr></thead><tbody><tr v-for="row in riskOutputs" :key="row.method_id"><td>{{ names[row.method_id] || row.method_id }}<small v-if="row.method_id === report.selection.selected_method_id">当前采用</small></td><td>{{ percent(row.claim_probability) }}</td><td>{{ number(row.conditional_mean_payout) }}</td><td>{{ number(row.expected_payout) }}</td><td>{{ row.p90_status === 'validated' ? number(row.p90_payout) : '—' }}<small>{{ label(row.p90_status) }}</small></td><td>{{ label(metrics?.models.find(model => model.method_id === row.method_id)?.release_state) }}<small>{{ label(row.reason_code) }}</small></td></tr></tbody></table></div>
              <section class="panel comparison-observed"><h2>价格情景参照</h2><p class="business-note">确定性情景 · 非预期赔款</p><table v-if="priceOutputs.length" class="business-table"><thead><tr><th>方法</th><th>参考价（元/吨）</th><th>情景赔款（元）</th></tr></thead><tbody><tr v-for="row in priceOutputs" :key="row.method_id"><td>{{ names[row.method_id] }}</td><td>{{ number(row.reference_price) }}</td><td>{{ number(row.scenario_payout) }}<small>{{ label(row.reason_code) }}</small></td></tr></tbody></table><p v-else>本报告未提供价格情景参照。</p></section>
            </template>
          </template>
        </template>
        <template v-else>
          <section class="panel"><h2>验证结论与选择依据</h2><p>{{ report.selection.selected_method_id ? `采用方法：${names[report.selection.selected_method_id] || report.selection.selected_method_id}` : '尚无已指定的可采用方法' }} · {{ label(report.selection.reason_code) }}</p><p class="business-note">{{ metrics?.sample_count }} 个样本 · {{ metrics?.date_count }} 个估值日 · 选择清单{{ report.selection.frozen ? '已冻结' : '未冻结' }}</p></section>
          <div class="panel table-scroll comparison-observed"><table class="business-table comparison-table"><thead><tr><th>方法 / 版本</th><th>目标覆盖率 / 失败数</th><th v-for="id in metricIds" :key="id">{{ label(id) }}</th><th>使用状态</th></tr></thead><tbody><tr v-for="model in metricModels" :key="model.method_id"><td>{{ names[model.method_id] || model.method_id }}<small>{{ model.model_version || '无模型工件' }}</small></td><td>{{ percent(model.coverage) }} / {{ model.failure_count }}<small v-if="model.coverage < 1">覆盖不完整，不能作为完整比较结论</small></td><td v-for="id in metricIds" :key="id"><template v-for="metric in model.metrics.filter(item => item.metric_id === id)" :key="metric.metric_id">{{ number(metric.value) }} {{ unit(metric.unit) }}<small>{{ metric.value === null ? label(metric.missing_reason) : metric.direction === 'lower_is_better' ? '越低越好' : metric.direction === 'higher_is_better' ? '越高越好' : metric.direction === 'closer_to_zero' ? '越接近零越好' : '诊断指标' }}</small></template><span v-if="!model.metrics.some(item => item.metric_id === id)">—</span></td><td>{{ label(model.release_state) }}<small>{{ label(model.reason_code) }}</small></td></tr></tbody></table></div>
          <section v-for="chart in evidence" :key="chart.view" class="panel comparison-observed"><h2>{{ label(chart.view) }}</h2><ComparisonCalibration v-if="chart.view === 'calibration'" :items="chart.items" /><ComparisonDataQuality v-if="chart.view === 'data_quality'" :items="chart.items" /><div v-else-if="chart.items.length" class="table-scroll"><table class="business-table"><thead><tr><th v-for="key in [...new Set(chart.items.flatMap(item => Object.keys(item)))]" :key="key">{{ label(key) }}</th></tr></thead><tbody><tr v-for="(row, index) in chart.items" :key="index"><td v-for="key in [...new Set(chart.items.flatMap(item => Object.keys(item)))]" :key="key">{{ cell(row[key]) }}</td></tr></tbody></table></div><p v-else class="business-note">暂无此项数据。</p></section>
        </template>
      </section>
      <details class="panel comparison-observed"><summary>数据与版本追溯</summary><dl class="comparison-details"><div><dt>报告 / 比较组</dt><dd>{{ report.run_id }} / {{ report.comparison_group_id }}</dd></div><div><dt>生成时间</dt><dd>{{ report.created_at }}</dd></div><div v-for="(value,key) in report.protocol" :key="key"><dt>{{ label(String(key)) }}</dt><dd>{{ cell(value) }}</dd></div></dl></details>
      <div class="comparison-download"><button class="select-btn" :disabled="exporting" @click="download('json')">下载报告 JSON</button><button class="select-btn" :disabled="exporting" @click="download('csv')">下载指标 CSV</button></div><p v-if="exportError" role="alert" class="error-banner">{{ exportError }}</p>
    </template>
  </div>
</template>
