<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
const emit = defineEmits<{ analyze: [ticker: string] }>()
defineProps<{ insurer: boolean }>()
interface Overview { ticker: string; as_of: string; latest_settlement: number; last_trade_date: string; tickers: { ticker: string; last_trade_date: string }[]; series: { date: string; settlement: number }[]; forecast: { status: string; reason: string | null; horizon_trading_days: number; methods: { method_id: string; value: number }[] }; validation: { sample_count: number; date_count: number; methods: { method_id: string; mae: number; rmse: number; bias: number }[]; backtest: { as_of: string; label_available_at: string; actual: number; price_last: number; price_ma20: number; price_ridge: number }[] }; warnings: string[] }
const ticker = ref('c2701'), data = ref<Overview | null>(null), loading = ref(false), error = ref('')
const names: Record<string, string> = { price_last: '最近结算价基线', price_ma20: '20 日均价基线', price_ridge: 'Ridge 价格预测' }
const money = (v: number | null | undefined) => v == null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(v)
let requestId = 0
async function load() { const id = ++requestId; loading.value = true; error.value = ''; data.value = null; try { const r = await fetch(`/api/v1/prices/overview?ticker=${encodeURIComponent(ticker.value)}`); if (!r.ok) throw new Error(`行情与预测暂不可用 (${r.status})，请重试。`); const body = await r.json(); if (id === requestId) data.value = body } catch (e) { if (id === requestId) error.value = e instanceof Error ? e.message : '加载失败' } finally { if (id === requestId) loading.value = false } }
const points = computed(() => data.value?.series ?? [])
const bounds = computed(() => { const p = points.value.map(p => p.settlement); return { low: Math.min(...p) - 20, high: Math.max(...p) + 20 } })
const y = (v: number) => 210 - (v - bounds.value.low) / (bounds.value.high - bounds.value.low) * 180
const line = computed(() => points.value.map((p, i) => `${65 + i / Math.max(points.value.length - 1, 1) * 695},${y(p.settlement)}`).join(' '))
const ticks = computed(() => Array.from({ length: 5 }, (_, i) => bounds.value.low + (bounds.value.high - bounds.value.low) * i / 4))
const dateTicks = computed(() => [...new Set([0, Math.floor(points.value.length / 2), points.value.length - 1])].filter(i => i >= 0).map(i => ({ index: i, date: points.value[i]?.date })))
onMounted(load)
</script>
<template>
  <div class="market-workspace">
    <div class="business-toolbar"><label>具体玉米合约<select v-model="ticker" :disabled="loading" @change="load"><option v-for="c in data?.tickers ?? [{ ticker: 'c2701' }, { ticker: 'c2611' }, { ticker: 'c2609' }]" :key="c.ticker" :value="c.ticker">{{ c.ticker.toUpperCase() }}</option></select></label><button class="select-btn" :disabled="loading" @click="load">刷新离线数据</button><button v-if="insurer" class="primary-btn" :disabled="loading || !data" @click="emit('analyze', ticker)">带入客户风险分析 →</button></div>
    <div v-if="error" class="error-banner" role="alert">{{ error }} <button class="text-btn" @click="load">重试加载</button></div><p v-if="loading" role="status">正在读取行情与价格预测…</p>
    <template v-if="data">
      <div class="source-banner source-live"><div><strong>真实期货历史快照 · {{ data.ticker.toUpperCase() }}</strong><small>截至 {{ data.as_of }} · 结算价 {{ money(data.latest_settlement) }} 元/吨 · 最后交易日 {{ data.last_trade_date }} · 非实时</small></div></div>
      <section class="panel large-chart"><div class="panel-heading"><h2>具体合约结算价历史（元/吨）</h2></div><div class="chart-wrap"><svg viewBox="0 0 800 260" role="img" :aria-label="`${data.ticker}历史结算价，${points[0]?.date}至${data.as_of}`"><g v-for="v in ticks" :key="v"><line x1="65" x2="760" :y1="y(v)" :y2="y(v)" class="grid-line"/><text x="55" :y="y(v) + 4" text-anchor="end" class="chart-axis">{{ Math.round(v) }}</text></g><polyline :points="line" fill="none" class="price-line"/><text v-for="t in dateTicks" :key="t.index" :x="65 + t.index / Math.max(points.length - 1, 1) * 695" y="240" :text-anchor="t.index === 0 ? 'start' : t.index === points.length - 1 ? 'end' : 'middle'" class="chart-axis">{{ t.date }}</text></svg></div></section>
      <h2 class="section-title">未来 20 个交易日平均结算价 · 三方法参考</h2>
      <div v-if="data.forecast.status !== 'available'" class="disclaimer">当前合约不提供前瞻价格预测：{{ data.forecast.reason }}。可切换 C2701 查看。</div>
      <section v-else class="price-method-grid"><article v-for="m in data.forecast.methods" :key="m.method_id" class="forecast-card"><small>{{ names[m.method_id] ?? m.method_id }}</small><strong>{{ money(m.value) }} <small>元/吨</small></strong><span>{{ m.method_id === 'price_ridge' ? '研究预测' : '基准参照' }}</span></article></section>
      <section class="panel records-panel"><h2 class="section-title">历史验证：预测与实际均价</h2><p class="business-note">验证集 · {{ data.validation.sample_count }} 个样本 · {{ data.validation.date_count }} 个估值日</p><div class="table-scroll"><table class="business-table"><thead><tr><th>方法</th><th>平均绝对误差 MAE</th><th>均方根误差 RMSE</th><th>平均偏差</th></tr></thead><tbody><tr v-for="m in data.validation.methods" :key="m.method_id"><td>{{ names[m.method_id] ?? m.method_id }}</td><td>{{ money(m.mae) }} 元/吨</td><td>{{ money(m.rmse) }} 元/吨</td><td>{{ money(m.bias) }} 元/吨</td></tr></tbody></table></div>
      <details class="calculation-details"><summary>查看逐期历史预测与实际值</summary><div class="table-scroll"><table class="business-table"><thead><tr><th>历史估值日</th><th>观察期结束</th><th>实际均价</th><th>最近价基线</th><th>均价基线</th><th>Ridge 预测</th></tr></thead><tbody><tr v-for="p in data.validation.backtest" :key="p.as_of"><td>{{ p.as_of }}</td><td>{{ p.label_available_at }}</td><td>{{ money(p.actual) }}</td><td>{{ money(p.price_last) }}</td><td>{{ money(p.price_ma20) }}</td><td>{{ money(p.price_ridge) }}</td></tr></tbody></table></div></details></section>
      <details class="calculation-details"><summary>数据与预测口径</summary><p>未来 20 个交易日平均结算价的点预测，非逐日路径或保单结算价。历史快照，最终测试尚未发布。</p></details>
    </template>
  </div>
</template>
