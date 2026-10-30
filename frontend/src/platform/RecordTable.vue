<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BusinessRecord, Column } from './types'
import { date, fmt, label, tone } from './labels'
import Icon from './Icon.vue'
const props = withDefaults(defineProps<{ records: BusinessRecord[]; columns: Column[]; title?: string; searchable?: boolean; empty?: string; selectable?: boolean }>(), { searchable: true, empty: '当前条件下暂无记录', selectable: true })
const emit = defineEmits<{ select: [record: BusinessRecord]; export: [records: BusinessRecord[]] }>()
const search = ref(''), status = ref(''), sortKey = ref(''), ascending = ref(true), page = ref(1)
const statuses = computed(() => [...new Set(props.records.map(r => r.status).filter(Boolean))])
const filtered = computed(() => {
 const query = search.value.trim().toLowerCase()
 const rows = props.records.filter(r => (!status.value || r.status === status.value) && (!query || JSON.stringify(r).toLowerCase().includes(query)))
 if (sortKey.value) rows.sort((a,b) => { const av = a[sortKey.value], bv = b[sortKey.value]; return (typeof av === 'number' && typeof bv === 'number' ? av-bv : String(av || '').localeCompare(String(bv || ''), 'zh-CN')) * (ascending.value ? 1 : -1) })
 return rows
})
const pageCount = computed(() => Math.max(1,Math.ceil(filtered.value.length / 8)))
const paged = computed(() => filtered.value.slice((Math.min(page.value,pageCount.value)-1)*8, Math.min(page.value,pageCount.value)*8))
function format(value: unknown, kind?: string) { if (kind === 'status') return label(value); if (kind === 'date') return date(value); if (kind === 'percent') return value == null ? '—' : `${fmt(Number(value)*100,4)}%`; if (['money','number','tons'].includes(kind || '')) return value == null ? '—' : `${kind === 'money' ? '¥ ' : ''}${fmt(value)}${kind === 'tons' ? ' 吨' : ''}`; return value == null || value === '' ? '—' : typeof value === 'object' ? (Array.isArray(value) ? value.join('、') : '查看详情') : label(value) }
function sort(key: string) { ascending.value = sortKey.value === key ? !ascending.value : true; sortKey.value = key }
</script>
<template>
<section class="gg-ledger">
  <div v-if="title || searchable" class="gg-table-tools">
    <div class="gg-table-title"><h3 v-if="title">{{ title }}</h3><span>{{ filtered.length }} 条记录</span></div>
    <div v-if="searchable" class="gg-table-controls">
      <label class="gg-search"><Icon name="search" :size="16"/><input v-model="search" aria-label="搜索当前列表" placeholder="搜索编号、客户或业务内容" @input="page=1" /></label>
      <select v-if="statuses.length" v-model="status" aria-label="筛选业务状态" @change="page=1"><option value="">全部状态</option><option v-for="s in statuses" :key="s" :value="s">{{ label(s) }}</option></select>
      <button class="gg-btn gg-btn-quiet" @click="emit('export',filtered)"><Icon name="download" :size="15"/>导出</button>
    </div>
  </div>
  <div class="gg-table-overflow"><table class="gg-table"><thead><tr><th v-for="col in columns" :key="col.key" :style="{minWidth:col.width}" @click="sort(col.key)"><button>{{ col.label }}<span class="gg-sort">{{ sortKey===col.key ? (ascending?'↑':'↓') : '↕' }}</span></button></th><th v-if="selectable" class="gg-table-operation">操作</th></tr></thead><tbody>
    <tr v-for="record in paged" :key="record.id" :class="{ 'gg-clickable': selectable }" @click="selectable && emit('select',record)">
      <td v-for="(col,i) in columns" :key="col.key" :class="{ 'gg-primary-cell':i===0,'gg-numeric': ['number','tons','money','percent'].includes(col.format || '') }">
        <span v-if="col.format==='status'" class="gg-badge" :class="`gg-${tone(record[col.key])}`"><i/>{{ label(record[col.key]) }}</span><template v-else>{{ format(record[col.key],col.format) }}</template><small v-if="col.secondary">{{ format(record[col.secondary]) }}</small>
      </td><td v-if="selectable"><button class="gg-text-btn" @click.stop="emit('select',record)">查看<Icon name="chevron" :size="13"/></button></td>
    </tr>
    <tr v-if="!filtered.length"><td :colspan="columns.length+(selectable?1:0)"><div class="gg-empty"><Icon name="file" :size="28"/><strong>{{ empty }}</strong><span>可调整查询条件，或通过页面操作创建业务记录。</span></div></td></tr>
  </tbody></table></div>
  <div class="gg-table-foot"><span>显示 {{ filtered.length ? (Math.min(page,pageCount)-1)*8+1 : 0 }}–{{ Math.min(Math.min(page,pageCount)*8,filtered.length) }} / {{ filtered.length }} 条</span><div><button aria-label="上一页" :disabled="page<=1" @click="page--">‹</button><span>{{ Math.min(page,pageCount) }} / {{ pageCount }}</span><button aria-label="下一页" :disabled="page>=pageCount" @click="page++">›</button></div></div>
</section>
</template>
