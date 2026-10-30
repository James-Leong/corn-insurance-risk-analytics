<script setup lang="ts">
import { computed } from 'vue'
import { fmt } from './labels'
const props=withDefaults(defineProps<{ points:{date:string,value:number|null}[]; unit?:string; color?:string; height?:number }>(),{color:'#5962b0',height:230})
const valid=computed(()=>props.points.filter(p=>p.value!=null && Number.isFinite(p.value)))
const min=computed(()=>valid.value.length?Math.min(...valid.value.map(p=>p.value as number)):0)
const max=computed(()=>valid.value.length?Math.max(...valid.value.map(p=>p.value as number)):1)
const ratioUnit=computed(()=>['比例','ratio','fraction'].includes(props.unit||''))
const axisValue=(value:number)=>ratioUnit.value?`${fmt(value*100,4)}%`:fmt(value,1)
const padding=computed(()=>(max.value-min.value)*.15 || max.value*.01 || 1)
const y=(v:number)=>18+(1-(v-min.value+padding.value)/(max.value-min.value+padding.value*2))*(props.height-55)
const x=(i:number)=>62+(i/Math.max(props.points.length-1,1))*680
const path=computed(()=>{let d='',gap=true;props.points.forEach((p,i)=>{if(p.value==null){gap=true;return}d+=`${gap?'M':'L'}${x(i).toFixed(2)},${y(p.value).toFixed(2)} `;gap=false});return d})
</script>
<template><div class="gg-chart"><svg v-if="valid.length" viewBox="0 0 780 240" role="img" :aria-label="`数据序列图，${unit || ''}，${points.length}个观测`"><g v-for="n in 5" :key="n"><line x1="62" x2="750" :y1="18+(n-1)*45" :y2="18+(n-1)*45" stroke="#edf0f5"/><text x="52" :y="22+(n-1)*45" text-anchor="end" class="gg-axis">{{ axisValue(max+padding-(n-1)*(max-min+padding*2)/4) }}</text></g><path :d="path" fill="none" :stroke="color" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/><text v-for="i in [0,Math.floor((points.length-1)/2),points.length-1]" :key="i" :x="x(i)" y="229" text-anchor="middle" class="gg-axis">{{ points[i]?.date }}</text></svg><div v-else class="gg-empty"><strong>当前数据不可绘图</strong><span>暂无有效观测值，缺失数据不会补零。</span></div></div></template>
