<script setup lang="ts">
import { computed } from 'vue'
import type { MarketData } from '../types/api'
const props = defineProps<{ data: MarketData | null }>()
const points = computed(() => props.data?.series.slice(-40) ?? [])
const line = computed(() => {
  if (!points.value.length) return ''
  const values = points.value.map(point => point.price)
  const low = Math.min(...values) - 10
  const high = Math.max(...values) + 10
  return values.map((value, index) => `${index / Math.max(values.length - 1, 1) * 700},${190 - (value - low) / (high - low) * 170}`).join(' ')
})
</script>
<template>
  <div class="chart-wrap">
    <svg viewBox="0 0 700 210" role="img" aria-label="近40个样本行情折线">
      <line v-for="y in [20,75,130,185]" :key="y" x1="0" :y1="y" x2="700" :y2="y" class="grid-line" />
      <polyline v-if="line" :points="line" fill="none" class="price-line" />
    </svg>
    <div class="chart-foot"><span>近 {{ points.length }} 个样本</span><span>单位：{{ data?.unit ?? '元/吨' }}</span></div>
  </div>
</template>
