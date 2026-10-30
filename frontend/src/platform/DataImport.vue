<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { request } from './api'
import Icon from './Icon.vue'

defineProps<{ projectId?: string }>()
type ImportResponse = {
  id?: string
  status: string
  row_count: number
  content_hash: string
  rows?: Record<string, unknown>[]
  warnings?: string[]
  duplicate?: boolean
  release_identity?: Record<string, unknown>
  data?: { observations?: Record<string, unknown>[] }
}
type ImportPayload = {
  mode: 'preview' | 'confirm'
  source_id: string
  name: string
  source_uri: string
  source_published_at: string
  source_revision: string
  kind: 'trade' | 'supply_demand'
  period_type: 'calendar_month' | 'calendar_year' | 'MY' | 'TY'
  unit: string
  is_fixture: boolean
  rows?: Record<string, unknown>[]
  csv_content?: string
}
const emit = defineEmits<{ close: []; imported: [result: ImportResponse] }>()
const maxBytes = 2_000_000
const fields = reactive({
  source_id: '', name: '', source_uri: '', source_published_at: '', source_revision: '',
  kind: 'trade' as 'trade' | 'supply_demand',
  period_type: 'calendar_month' as ImportPayload['period_type'], unit: '吨', is_fixture: false,
})
const format = ref<'json' | 'csv'>('csv')
const content = ref(''), fileName = ref(''), error = ref(''), busy = ref(false)
const result = ref<ImportResponse | null>(null)
const reviewedInput = ref(''), reviewedPayload = ref<ImportPayload | null>(null)
const firstInput = ref<HTMLInputElement | null>(null)
const currentInput = computed(() => JSON.stringify({ fields, format: format.value, content: content.value }))
const canConfirm = computed(() => !!result.value?.content_hash && currentInput.value === reviewedInput.value && !busy.value)
const periodOptions = computed(() => fields.kind === 'trade'
  ? [{ value: 'calendar_month', label: '自然月（当月）' }, { value: 'calendar_year', label: '自然年（全年）' }]
  : [{ value: 'MY', label: '本国市场年度 MY' }, { value: 'TY', label: '统一贸易年度 TY' }])
const header = computed(() => fields.kind === 'trade'
  ? 'reporter,partner,flow,hs_code,hs_revision,period_start,period_end,value'
  : 'entity_code,metric,marketing_year,period_start,period_end,value')
const previewRows = computed(() => (result.value?.rows || result.value?.data?.observations || []).slice(0, 20))
const previewColumns = computed(() => {
  const keys = new Set(previewRows.value.flatMap(row => Object.keys(row)))
  return ['reporter', 'partner', 'flow', 'hs_code', 'entity_code', 'metric', 'marketing_year', 'period_start', 'period_end', 'value']
    .filter(key => keys.has(key))
})
const columnLabels: Record<string, string> = {
  reporter: '报告国', partner: '伙伴', flow: '流向', hs_code: 'HS编码', entity_code: '国家',
  metric: '指标', marketing_year: '年度', period_start: '统计起日', period_end: '统计止日', value: '数值',
}

watch(() => fields.kind, kind => { fields.period_type = kind === 'trade' ? 'calendar_month' : 'MY' })
watch(currentInput, () => {
  result.value = null
  reviewedInput.value = ''
  reviewedPayload.value = null
}, { flush: 'sync' })

async function readFile(event: Event) {
  error.value = ''
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  result.value = null
  if (file.size > maxBytes) {
    error.value = '文件超过 2 MB，请缩小数据范围后重新选择。'
    input.value = ''
    return
  }
  const extension = file.name.split('.').at(-1)?.toLowerCase()
  if (!['csv', 'json'].includes(extension || '')) {
    error.value = '请选择 UTF-8 编码的 CSV 或 JSON 文件。'
    input.value = ''
    return
  }
  busy.value = true
  try {
    const text = (await file.text()).replace(/^\uFEFF/, '')
    if (text.includes('\uFFFD')) throw new Error('文件可能不是 UTF-8 编码，请转换编码后重新上传。')
    if (new TextEncoder().encode(text).length > maxBytes) throw new Error('文件内容超过 2 MB。')
    format.value = extension as 'csv' | 'json'
    content.value = text
    fileName.value = file.name
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '读取文件失败，请重新选择。'
    input.value = ''
  } finally { busy.value = false }
}

function buildPayload(): ImportPayload {
  if (!fields.name.trim() || !fields.source_revision.trim() || !fields.source_published_at) {
    throw new Error('请填写数据名称、发布日期和发布修订号。')
  }
  if (!/^[a-zA-Z0-9_-]{1,40}$/.test(fields.source_id)) throw new Error('来源标识限 1 至 40 位字母、数字、下划线或短横线。')
  let uri: URL
  try { uri = new URL(fields.source_uri) } catch { throw new Error('请输入可追溯的原文 HTTP(S) 链接。') }
  if (!['http:', 'https:'].includes(uri.protocol)) throw new Error('原文链接仅支持 HTTP 或 HTTPS。')
  if (!content.value.trim()) throw new Error('请选择文件或粘贴需要导入的数据内容。')
  if (new TextEncoder().encode(content.value).length > maxBytes) throw new Error('数据内容超过 2 MB，请缩小范围。')
  const payload: ImportPayload = { mode: 'preview', ...fields }
  if (format.value === 'csv') payload.csv_content = content.value
  else {
    let parsed: unknown
    try { parsed = JSON.parse(content.value) } catch { throw new Error('JSON 格式错误，请使用记录数组或包含 rows 数组的对象。') }
    const rows = Array.isArray(parsed) ? parsed : parsed && typeof parsed === 'object' ? (parsed as { rows?: unknown }).rows : null
    if (!Array.isArray(rows) || !rows.length || rows.length > 5000) throw new Error('JSON 需要包含 1 至 5000 条记录。')
    if (rows.some(row => !row || typeof row !== 'object' || Array.isArray(row))) throw new Error('每条 JSON 记录必须是字段对象。')
    payload.rows = rows as Record<string, unknown>[]
  }
  return payload
}

async function previewImport() {
  error.value = ''
  result.value = null
  reviewedInput.value = ''
  reviewedPayload.value = null
  try {
    const payload = buildPayload()
    const inputAtRequest = currentInput.value
    busy.value = true
    const response = await request<ImportResponse>('/data/imports', payload)
    if (currentInput.value !== inputAtRequest) throw new Error('输入已发生变化，请重新预览。')
    if (!response.content_hash) throw new Error('服务端未返回内容校验值，暂不能确认导入。')
    result.value = response
    reviewedInput.value = inputAtRequest
    reviewedPayload.value = JSON.parse(JSON.stringify(payload)) as ImportPayload
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '数据预览失败。'
  } finally { busy.value = false }
}

async function confirmImport() {
  error.value = ''
  if (!canConfirm.value || !reviewedPayload.value || !result.value) {
    error.value = '请先预览当前输入；修改任意字段或内容后必须重新预览。'
    return
  }
  const expectedHash = result.value.content_hash
  busy.value = true
  try {
    const response = await request<ImportResponse>('/data/imports', { ...reviewedPayload.value, mode: 'confirm' })
    if (response.content_hash !== expectedHash) throw new Error('返回版本与预览校验值不一致，请刷新目录核对后再处理。')
    emit('imported', response)
    emit('close')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '确认导入失败，请核对版本后重试。'
  } finally { busy.value = false }
}

function close() { if (!busy.value) emit('close') }
const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') close() }
onMounted(() => { document.addEventListener('keydown', onKey); firstInput.value?.focus() })
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div class="gg gg-overlay" @click.self="close">
      <section class="gg-modal gg-data-import" role="dialog" aria-modal="true" aria-labelledby="data-import-title">
        <header>
          <div><span class="gg-overline">数据与研究 · 标准文件接入</span><h2 id="data-import-title">导入玉米外部数据</h2></div>
          <button class="gg-icon-btn" aria-label="关闭数据导入" :disabled="busy" @click="close"><Icon name="close" /></button>
        </header>
        <p class="gg-modal-description">上传贸易或国别供需文件，先核验字段和口径，再保存不可变发布版本。人工导入不代表原机构已经核验，未提供的字段保持缺失。</p>
        <form @submit.prevent="previewImport">
          <div class="gg-form-grid">
            <label class="gg-field"><span>数据名称 *</span><input ref="firstInput" v-model="fields.name" required maxlength="120" :disabled="busy" placeholder="如：中国玉米月度进口来源" /></label>
            <label class="gg-field"><span>来源标识 *</span><input v-model="fields.source_id" required maxlength="40" pattern="[a-zA-Z0-9_-]+" :disabled="busy" placeholder="如：customs_import" /><small>使用字母、数字、下划线或短横线</small></label>
            <label class="gg-field gg-field-wide"><span>原文／原始文件链接 *</span><input v-model="fields.source_uri" type="url" required maxlength="1000" :disabled="busy" placeholder="https://…" /><small>用于追溯，不会由平台自动下载</small></label>
            <label class="gg-field"><span>来源发布日期 *</span><input v-model="fields.source_published_at" type="date" required :disabled="busy" /></label>
            <label class="gg-field"><span>发布批次／修订号 *</span><input v-model="fields.source_revision" required maxlength="80" :disabled="busy" placeholder="如：2026-09-final-v1" /><small>相同版本不能覆盖为不同内容</small></label>
            <label class="gg-field"><span>数据类型 *</span><select v-model="fields.kind" required :disabled="busy"><option value="trade">玉米进出口贸易</option><option value="supply_demand">国别玉米供需</option></select></label>
            <label class="gg-field"><span>统计年度口径 *</span><select v-model="fields.period_type" required :disabled="busy"><option v-for="period in periodOptions" :key="period.value" :value="period.value">{{ period.label }}</option></select></label>
            <label class="gg-field"><span>数值单位 *</span><select v-model="fields.unit" required :disabled="busy"><option value="吨">吨</option><option value="千吨">千吨</option><option value="万吨">万吨</option><option value="kg">千克 kg</option><template v-if="fields.kind === 'trade'"><option value="USD">美元 USD</option><option value="CNY">人民币 CNY</option></template></select></label>
            <label class="gg-field"><span>文件格式 *</span><select v-model="format" required :disabled="busy"><option value="csv">UTF-8 CSV</option><option value="json">JSON 记录数组</option></select></label>
            <div class="gg-field gg-field-wide"><span>选择本地文件</span><input type="file" accept=".csv,.json,text/csv,application/json" aria-label="选择玉米数据文件" :disabled="busy" @change="readFile" /><small>{{ fileName || '支持 CSV / JSON，最大 2 MB，每批最多 5000 条记录。也可以直接粘贴内容。' }}</small></div>
            <label class="gg-field gg-field-wide"><span>数据内容 *</span><textarea v-model="content" rows="7" required :disabled="busy" spellcheck="false" :placeholder="format === 'csv' ? header : '[{…}] 或 {&quot;rows&quot;:[{…}]}，不读取对象中的来源元数据'" /><small>CSV 首行：{{ header }}</small></label>
            <div class="gg-field gg-field-wide"><div class="gg-checkbox"><input id="data-import-fixture" v-model="fields.is_fixture" type="checkbox" :disabled="busy" /><label for="data-import-fixture">仅用于研究参考，不作为合同采价依据</label></div><small>单独归档此批次，便于与后续发布版本核对。</small></div>
          </div>
          <div class="gg-notice"><Icon name="info" :size="17" /><span v-if="fields.kind === 'trade'">仅接收玉米原粮 HS1005、100510、100590。父项与子项、世界伙伴与逐国伙伴不能同时聚合；当月与累计不能混用。</span><span v-else>MY 和 TY 分开；逐行填写实际年度起止日期。同年度消费与出口齐全后计算用途比例，缺库存不生成库存比例。</span></div>
          <div v-if="error" class="gg-error" role="alert"><Icon name="warning" :size="18" /><span>{{ error }}</span></div>
          <section v-if="result" class="gg-import-preview" aria-live="polite">
            <h3>{{ result.duplicate ? '该内容已存在，确认后复用原版本' : '预览通过，尚未写入数据目录' }}</h3>
            <div class="gg-import-summary"><strong>{{ result.row_count }} 条记录</strong><span>{{ fields.is_fixture ? '合成验收数据 · fixture' : '人工外部文件 · 未核验' }}</span><span>预览前 {{ previewRows.length }} 行</span></div>
            <p v-for="warning in result.warnings" :key="warning" class="gg-import-help">{{ warning }}</p>
            <div v-if="previewRows.length" class="gg-import-table-wrap"><table class="gg-import-table"><thead><tr><th v-for="column in previewColumns" :key="column">{{ columnLabels[column] || column }}</th></tr></thead><tbody><tr v-for="(row, index) in previewRows" :key="index"><td v-for="column in previewColumns" :key="column">{{ row[column] ?? '缺失' }}</td></tr></tbody></table></div>
            <details class="gg-query-advanced"><summary>发布口径与内容 SHA256</summary><pre class="gg-json">{{ JSON.stringify(result.release_identity, null, 2) }}
{{ result.content_hash }}</pre></details>
            <p class="gg-import-help">确认后生成只读版本。修改任意来源字段、格式或数据内容都会使预览失效。</p>
          </section>
          <footer>
            <span>{{ projectId ? `当前项目 ${projectId} · ` : '' }}公共玉米数据目录</span>
            <div>
              <button type="button" class="gg-btn" :disabled="busy" @click="close">取消</button>
              <button type="submit" class="gg-btn" :disabled="busy"><span v-if="busy" class="gg-spinner" />{{ result ? '重新预览' : '校验并预览' }}</button>
              <button type="button" class="gg-btn gg-btn-primary" :disabled="!canConfirm" @click="confirmImport">确认导入<Icon name="arrow" :size="16" /></button>
            </div>
          </footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.gg-data-import{width:900px}.gg-import-summary{display:flex;flex-wrap:wrap;gap:9px 18px;margin:10px 0;color:var(--muted);font-size:11px}.gg-import-summary strong{color:var(--ink);font-weight:500}.gg-import-help{color:var(--muted);font-size:11px;line-height:1.9;margin:9px 0}.gg-import-table-wrap{overflow:auto;max-height:270px;border:1px solid var(--line);border-radius:6px;margin-top:12px}.gg-import-table{width:100%;border-collapse:collapse;text-align:left;white-space:nowrap;font-size:11px}.gg-import-table th,.gg-import-table td{padding:9px 11px;border-bottom:1px solid var(--line)}.gg-import-table th{position:sticky;top:0;background:#f7f7fb;color:var(--muted);font-weight:500}.gg-data-import textarea{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:11px}.gg-import-preview{margin-top:18px}.gg-import-preview h3{color:var(--ink)}.gg-data-import footer{flex-wrap:wrap}@media(max-width:600px){.gg-data-import footer>div{flex-wrap:wrap;width:100%}.gg-data-import footer button{flex:1}}
</style>
