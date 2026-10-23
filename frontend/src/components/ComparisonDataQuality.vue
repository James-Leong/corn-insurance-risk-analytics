<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ items: Record<string, unknown>[] }>()
const summaries = computed(() => props.items.map(item => {
  const detail = item.detail as Record<string, unknown> | undefined
  if (item.check === 'purged_date_split') return {
    title: item.status === 'passed' ? '时间切分检查通过' : '时间切分检查待核验',
    description: `已清除 ${detail?.purged_count ?? '—'} 条观察窗跨越分区边界的样本；校准从 ${detail?.calibration_start ?? '—'} 开始，验证从 ${detail?.validation_start ?? '—'} 开始。${detail?.test_opened === false ? '最终测试尚未打开。' : ''}`,
  }
  if (item.check === 'source_quality' && detail) {
    const contracts = Object.entries(detail) as [string, {missing_open_dates?: string[]; rows?: number; first_date?: string; last_date?: string}][]
    const missing = contracts.reduce((sum, [, value]) => sum + (value.missing_open_dates?.length || 0), 0)
    return { title: `${contracts.length} 个具体合约 · ${missing === 0 ? '无缺失交易日' : `缺失 ${missing} 个交易日`}`, description: contracts.map(([name, value]) => `${name}：${value.rows ?? '—'} 行（${value.first_date ?? '—'} 至 ${value.last_date ?? '—'}）`).join('；') }
  }
  return {title: '数据检查记录', description: '详细检查结果见技术详情。'}
}))
</script>
<template><div v-if="items.length"><div v-for="(summary,index) in summaries" :key="index" class="quality-summary"><strong>{{ summary.title }}</strong><p class="business-note">{{ summary.description }}</p></div><details><summary>查看完整数据检查记录（技术详情）</summary><pre>{{ JSON.stringify(items,null,2) }}</pre></details></div><p v-else class="business-note">当前报告未提供数据检查证据。</p></template>
<style scoped>.quality-summary{border-bottom:1px solid #edf0ed;padding:14px 0}.quality-summary strong{font-size:13px;color:#354b3b}.quality-summary p{margin-bottom:0}details{margin-top:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;line-height:1.7;color:#748078;background:#f7f8f4;padding:14px;border-radius:6px}</style>
