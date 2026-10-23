<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { business, storageState, demoDate, projectSummary, advanceClaim, enrollMember, resetDemo, type Policy } from '../mockBusiness'
import type { Role } from '../workspaces'
const props = defineProps<{ role: Role; records: boolean }>()
const emit = defineEmits<{ navigate: []; scenario: [policy: Policy]; comparison: [] }>()
const search = ref('')
const region = ref('全部')
const status = ref('全部')
const selected = ref('')
const message = ref('')
const confirmingReset = ref(false)
const names = {farmer:'个人保单',cooperative:'成员保障台账',insurer:'承保与理赔台账',authority:'区域项目监管'}
const detailElement = ref<HTMLElement | null>(null)
const number = (n: number) => new Intl.NumberFormat('zh-CN', {maximumFractionDigits:2}).format(n)
const sum = (values: number[]) => values.reduce((a,b)=>a+b,0)
const percent = (n:number,d:number) => d > 0 ? `${number(n/d*100)}%` : '—'
const visibleProjects = computed(()=>business.projects.filter(p => (props.role !== 'farmer' && props.role !== 'cooperative') || p.id === 'PRJ-001'))
const projects = computed(()=>visibleProjects.value.filter(p=>region.value==='全部'||p.region===region.value).map(projectSummary))
const scopePolicies = computed(()=>business.policies.filter(p => props.role === 'farmer' ? p.memberId === 'F001' : projects.value.some(s=>s.project.id === p.projectId)))
const scopeMembers = computed(()=>business.members.filter(m=>projects.value.some(s=>s.project.id===m.projectId)))
const insuredMembers = computed(()=>scopeMembers.value.filter(m=>scopePolicies.value.some(p=>p.memberId===m.id)))
const eligiblePolicies = computed(()=>scopePolicies.value.filter(p=>p.status==='已结算' && p.payout>0))
const claimAmount = computed(()=>sum(eligiblePolicies.value.map(p=>p.payout)))
const paid = computed(()=>sum(eligiblePolicies.value.filter(p=>p.claim==='已支付').map(p=>p.payout)))
const subsidyBudget = computed(()=>sum(projects.value.map(s=>s.project.subsidyBudget)))
const subsidyPaid = computed(()=>sum(projects.value.map(s=>s.project.subsidyPaid)))
const target = computed(()=>sum(projects.value.map(s=>s.project.targetHouseholds)))
const targetArea = computed(()=>sum(projects.value.map(s=>s.project.targetArea)))
const insuredArea = computed(()=>sum(projects.value.map(s=>s.area)))
const stats = computed(()=> {
  const tons = sum(scopePolicies.value.map(p=>p.tons))
  if(props.role==='farmer') return [
    {label:'本季保障数量',value:number(tons),unit:'吨',note:`${scopePolicies.value.length} 份模拟保单，含已结算`},
    {label:'保障中的数量',value:number(sum(scopePolicies.value.filter(p=>p.status==='保障中').map(p=>p.tons))),unit:'吨',note:'按保单保障状态统计'},
    {label:'结算应赔金额',value:number(claimAmount.value),unit:'元',note:'按结算条款计算，含待办理金额'},
    {label:'已到账赔付',value:number(paid.value),unit:'元',note:'模拟已支付记录合计'}]
  if(props.role==='cooperative') return [
    {label:'成员参保率',value:percent(insuredMembers.value.length,scopeMembers.value.length),unit:'',note:`${insuredMembers.value.length} / ${scopeMembers.value.length} 户已建档成员`},
    {label:'成员保障数量',value:number(tons),unit:'吨',note:'逐份保单数量汇总，含已结算'},
    {label:'待参保成员',value:number(scopeMembers.value.length-insuredMembers.value.length),unit:'户',note:'已建档但尚无保单的成员'},
    {label:'待到账赔付',value:number(claimAmount.value-paid.value),unit:'元',note:'结算应赔金额减已支付金额'}]
  if(props.role==='insurer') return [
    {label:'项目保费收入',value:number(sum(projects.value.map(s=>s.project.premium))),unit:'元',note:'模拟项目保费入账合计'},
    {label:'结算应赔责任',value:number(claimAmount.value),unit:'元',note:'已结算保单应赔合计'},
    {label:'待审核案件',value:number(scopePolicies.value.filter(p=>p.claim==='待审核').length),unit:'件',note:'可进入保单详情审核'},
    {label:'已支付赔付',value:number(paid.value),unit:'元',note:'支付操作同步更新各角色台账'}]
  return [
    {label:'目标农户覆盖率',value:percent(insuredMembers.value.length,target.value),unit:'',note:`已保障 ${insuredMembers.value.length} 户 / 目标 ${target.value} 户`},
    {label:'目标面积覆盖率',value:percent(insuredArea.value,targetArea.value),unit:'',note:`已保障 ${number(insuredArea.value)} / 目标 ${number(targetArea.value)} 亩`},
    {label:'补贴预算执行率',value:percent(subsidyPaid.value,subsidyBudget.value),unit:'',note:`已拨付 ${number(subsidyPaid.value)} / 预算 ${number(subsidyBudget.value)} 元`},
    {label:'赔付兑现率',value:percent(paid.value,claimAmount.value),unit:'',note:`已支付 ${number(paid.value)} / 应赔 ${number(claimAmount.value)} 元`}]
})
const policyRows = computed(()=>scopePolicies.value.filter(p=>{
 const member=business.members.find(m=>m.id===p.memberId)!
 return `${p.id} ${member.name}`.includes(search.value.trim()) && (status.value==='全部'||p.status===status.value||p.claim===status.value)
}))
const memberRows = computed(()=>scopeMembers.value.filter(m=>`${m.name} ${m.id}`.includes(search.value.trim()) && (status.value==='全部'|| (scopePolicies.value.some(p=>p.memberId===m.id) ? '已参保':'未参保')===status.value)))
const projectRows = computed(()=>projects.value.filter(s=>`${s.project.id} ${s.project.name} ${s.project.cooperative}`.includes(search.value.trim()) && (status.value==='全部'|| (s.project.subsidyPaid < s.project.subsidyBudget ? '补贴待拨付':'补贴已拨足')===status.value)))
const options = computed(()=>props.role==='cooperative'?['已参保','未参保']:props.role==='authority'?['补贴待拨付','补贴已拨足']:['保障中','已结算','未申请','待审核','待支付','已支付'])
const detailPolicy = computed(()=>scopePolicies.value.find(p=>p.id===selected.value))
const detailMember = computed(()=>scopeMembers.value.find(m=>m.id===selected.value))
const detailProject = computed(()=>projects.value.find(s=>s.project.id===selected.value))
const detailPolicies = computed(()=>detailPolicy.value ? [detailPolicy.value] : detailMember.value ? scopePolicies.value.filter(p=>p.memberId===detailMember.value!.id) : detailProject.value?.policies ?? [])
const attention = computed(()=>projects.value.flatMap(s=>{
 const list: string[]=[]
 if(s.insured.length<s.project.targetHouseholds) list.push(`${s.project.region}：距离覆盖目标还差 ${s.project.targetHouseholds-s.insured.length} 户`)
 if(s.project.subsidyPaid<s.project.subsidyBudget) list.push(`${s.project.region}：补贴待拨付 ${number(s.project.subsidyBudget-s.project.subsidyPaid)} 元`)
 if(s.due>s.paid) list.push(`${s.project.region}：待兑现赔付 ${number(s.due-s.paid)} 元`)
 return list
}))
watch(()=>props.role,()=>{search.value='';region.value='全部';status.value='全部';selected.value='';message.value='';confirmingReset.value=false})
watch([region,search,status],()=>{selected.value=''})
watch(()=>props.records, records => { if (!records) selected.value='' })
async function openRecord(id: string) {
  if (!props.records) {
    search.value=''
    status.value='全部'
    emit('navigate')
    await nextTick()
  }
  selected.value=id
}
watch(selected, async value => {
  if (!value) return
  await nextTick()
  detailElement.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  detailElement.value?.focus({ preventScroll: true })
})
function act(policy:Policy) {
 if(props.role==='farmer' && (policy.memberId!=='F001'||policy.claim!=='未申请')) return
 if(props.role!=='farmer' && props.role!=='insurer') return
 if(props.role==='insurer' && !['待审核','待支付'].includes(policy.claim)) return
 advanceClaim(policy)
 message.value=`${policy.id} 已更新为“${policy.claim}”（模拟操作）。`
}
function enroll(id:string) {
 const member=scopeMembers.value.find(m=>m.id===id)
 if(!member||props.role!=='cooperative') return
 enrollMember(member);message.value=`已为 ${member.name} 建立本季模拟保单。`
}
function paySubsidy(id:string) {
 if(props.role!=='authority') return
 const project=business.projects.find(p=>p.id===id)
 if(project) {project.subsidyPaid=project.subsidyBudget;message.value=`${project.name} 剩余补贴已模拟拨付。`}
}
function reset() {resetDemo();selected.value='';confirmingReset.value=false;message.value='演示数据已恢复初始状态。'}
function exportCsv() {
 let rows: (string|number)[][]
 if(props.role==='cooperative') rows=[['成员编号','姓名','种植面积(亩)','预计产量(吨)','参保状态'],...memberRows.value.map(m=>[m.id,m.name,m.area,m.production,scopePolicies.value.some(p=>p.memberId===m.id)?'已参保':'未参保'])]
 else if(props.role==='authority') rows=[['项目','地区','已保障户数','目标户数','保障面积(亩)','目标面积(亩)','补贴预算(元)','已拨付(元)','应赔(元)','已支付(元)'],...projectRows.value.map(s=>[s.project.name,s.project.region,s.insured.length,s.project.targetHouseholds,s.area,s.project.targetArea,s.project.subsidyBudget,s.project.subsidyPaid,s.due,s.paid])]
 else rows=[['保单号','成员','保障数量(吨)','保障价(元/吨)','保单状态','理赔状态','结算应赔(元)'],...policyRows.value.map(p=>[p.id,business.members.find(m=>m.id===p.memberId)!.name,p.tons,p.guarantee,p.status,p.claim,p.payout])]
 const escape=(v:string|number)=>`"${String(v).replace(/"/g,'""')}"`
 const url=URL.createObjectURL(new Blob(['\uFEFFMock演示数据 · 非真实业务记录\r\n'+rows.map(r=>r.map(escape).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'}))
 const link=document.createElement('a');link.href=url;link.download=`Mock-${names[props.role]}-${demoDate}.csv`;link.click();URL.revokeObjectURL(url)
 message.value='已导出当前筛选范围的 Mock 数据。'
}
</script>

<template>
  <div class="business-workspace">
    <section v-if="role === 'insurer' && !records" class="panel market-summary"><div><h2>历史合同赔付风险评估</h2></div><button class="select-btn" @click="emit('comparison')">打开模型评估</button></section>
    <div class="mock-notice"><div><strong>模拟业务数据</strong><p>统计截至 {{ demoDate }} · {{ role==='farmer'?'当前农户：演示农户 001':role==='cooperative'?'当前组织：示范合作社 A':'本季示范项目' }} · 操作仅保存在本机浏览器</p></div><button class="select-btn" @click="confirmingReset=true">重置演示</button></div>
    <div v-if="confirmingReset" class="inline-confirm" role="alert"><span>恢复全部角色的初始保单、理赔和补贴数据？</span><button class="primary-btn" @click="reset">确认重置</button><button class="select-btn" @click="confirmingReset=false">取消</button></div>
    <p v-if="message" class="action-message" role="status">{{ message }}</p><p v-if="storageState.warning" role="alert">{{ storageState.warning }}</p>
    <div v-if="role==='authority'||role==='insurer'" class="business-toolbar"><label>地区范围<select v-model="region"><option>全部</option><option v-for="p in visibleProjects" :key="p.id">{{ p.region }}</option></select></label></div>
    <section v-if="!records" class="metrics-grid" aria-label="业务统计"><article v-for="stat in stats" :key="stat.label" class="metric-card"><div class="metric-label">{{ stat.label }}</div><div class="metric-value">{{ stat.value }}<small>{{ stat.unit }}</small></div><div class="metric-foot">{{ stat.note }}</div></article></section>

    <section v-if="!records" class="content-grid">
      <article class="panel" v-if="role==='farmer'"><div class="panel-heading"><h2>我的理赔进度</h2><button class="select-btn" @click="emit('navigate')">查看全部保单 →</button></div><div v-for="p in eligiblePolicies" :key="p.id" class="task-row"><div><strong>{{ p.id }} · {{ number(p.payout) }} 元</strong><p>{{ p.claim==='未申请'?'已结算，可提交理赔申请':p.claim }}</p></div><button class="select-btn" @click="openRecord(p.id)">查看 / 办理</button></div><p v-if="!eligiblePolicies.length" class="business-note">暂无已结算应赔保单。</p></article>
      <article class="panel" v-else-if="role==='cooperative'"><div class="panel-heading"><h2>成员参保跟进</h2><button class="select-btn" @click="emit('navigate')">打开成员台账 →</button></div><div v-for="m in scopeMembers.filter(m=>!scopePolicies.some(p=>p.memberId===m.id))" :key="m.id" class="task-row"><div><strong>{{ m.name }} · 未参保</strong><p>{{ number(m.area) }} 亩 · 预计产量 {{ number(m.production) }} 吨</p></div><button class="select-btn" @click="openRecord(m.id)">查看成员</button></div><p v-if="insuredMembers.length===scopeMembers.length" class="business-note">全部已建档成员已参保。</p></article>
      <article class="panel" v-else-if="role==='insurer'"><div class="panel-heading"><h2>理赔待办</h2><button class="select-btn" @click="emit('navigate')">打开理赔台账 →</button></div><div v-for="p in scopePolicies.filter(p=>['待审核','待支付'].includes(p.claim))" :key="p.id" class="task-row"><div><strong>{{ p.id }} · {{ p.claim }}</strong><p>{{ number(p.payout) }} 元 · {{ business.members.find(m=>m.id===p.memberId)?.name }}</p></div><button class="select-btn" @click="openRecord(p.id)">办理</button></div><p v-if="!scopePolicies.some(p=>['待审核','待支付'].includes(p.claim))" class="business-note">当前范围没有待办理案件。</p></article>
      <article class="panel" v-else><div class="panel-heading"><h2>政策落实跟进</h2><button class="select-btn" @click="emit('navigate')">查看区域项目 →</button></div><ul class="attention-list"><li v-for="item in attention" :key="item">{{ item }}</li></ul><p v-if="!attention.length" class="business-note">当前范围覆盖、拨付与赔付均已达到目标。</p></article>

      <article class="panel"><div class="panel-heading"><h2>{{ role==='authority'?'项目执行对比':role==='insurer'?'对冲资金与赔付':'保障分布' }}</h2></div>
        <template v-if="role==='authority'"><div v-for="s in projects" :key="s.project.id" class="coverage-row"><div><strong>{{ s.project.region }}</strong><span>{{ s.insured.length }} / {{ s.project.targetHouseholds }} 户</span></div><progress :value="s.insured.length" :max="s.project.targetHouseholds" :aria-label="`${s.project.region}农户覆盖`"></progress><button class="text-btn" @click="openRecord(s.project.id)">查看执行明细 →</button></div></template>
        <dl v-else-if="role==='insurer'" class="business-list"><div><dt>已投入期权成本</dt><dd>{{ number(sum(projects.map(s=>s.project.hedgeCost))) }} 元</dd></div><div><dt>期权当前估值</dt><dd>{{ number(sum(projects.map(s=>s.project.hedgeValue))) }} 元</dd></div><div><dt>估值变动（未实现）</dt><dd>{{ number(sum(projects.map(s=>s.project.hedgeValue-s.project.hedgeCost))) }} 元</dd></div></dl>
        <dl v-else class="business-list"><div><dt>保障中保单</dt><dd>{{ scopePolicies.filter(p=>p.status==='保障中').length }} 份</dd></div><div><dt>已结算保单</dt><dd>{{ scopePolicies.filter(p=>p.status==='已结算').length }} 份</dd></div><div><dt>本季赔付上限合计</dt><dd>{{ number(sum(scopePolicies.map(p=>p.cap))) }} 元</dd></div></dl>
        <p class="business-note">{{ role==='authority'?'覆盖率按目标户数计算，保障面积按保单逐户汇总，同户不超过建档面积。':role==='insurer'?'期权估值不是已到账收入；保费、期权资金与保险赔付分别列示。':'每份保单独立约定保障价和赔付上限；可从详情带入试算。' }}</p>
      </article>
    </section>

    <section v-if="records && role==='insurer'" class="panel project-ledger"><div class="panel-heading"><h2>项目保费与期权台账</h2></div><div class="table-scroll"><table class="business-table"><thead><tr><th>项目</th><th>保费收入</th><th>期权成本</th><th>期权估值</th><th>估值变动（未实现）</th><th>操作</th></tr></thead><tbody><tr v-for="s in projects" :key="s.project.id"><td>{{ s.project.name }}</td><td>{{ number(s.project.premium) }} 元</td><td>{{ number(s.project.hedgeCost) }} 元</td><td>{{ number(s.project.hedgeValue) }} 元</td><td>{{ number(s.project.hedgeValue-s.project.hedgeCost) }} 元</td><td><button class="text-btn" @click="openRecord(s.project.id)">查看项目</button></td></tr></tbody></table></div></section>

    <section v-if="records" class="panel records-panel">
      <div class="panel-heading"><h2>{{ names[role] }}</h2><button class="select-btn" @click="exportCsv">导出筛选结果 CSV</button></div>
      <div class="business-toolbar"><label class="search-field">搜索<input v-model="search" :placeholder="role==='authority'?'项目名称 / 编号 / 合作社':role==='cooperative'?'成员姓名 / 编号':'保单号 / 成员姓名'" type="search" /></label><label>状态<select v-model="status" aria-label="台账状态"><option>全部</option><option v-for="option in options" :key="option">{{ option }}</option></select></label></div>
      <div class="table-scroll">
        <table v-if="role==='farmer'||role==='insurer'" class="business-table"><thead><tr><th>保单编号</th><th>被保险人</th><th>保障数量</th><th>保障期限</th><th>保单状态</th><th>理赔进度</th><th>结算应赔</th><th>操作</th></tr></thead><tbody><tr v-for="p in policyRows" :key="p.id"><td>{{ p.id }}</td><td>{{ business.members.find(m=>m.id===p.memberId)?.name }}</td><td>{{ number(p.tons) }} 吨</td><td>{{ p.start }}<br />至 {{ p.end }}</td><td><span class="pill-soft">{{ p.status }}</span></td><td>{{ p.claim }}</td><td>{{ number(p.payout) }} 元</td><td><button class="text-btn" @click="openRecord(p.id)">查看详情</button></td></tr><tr v-if="!policyRows.length"><td colspan="8">没有符合筛选条件的保单，请调整搜索或状态。</td></tr></tbody></table>
        <table v-else-if="role==='cooperative'" class="business-table"><thead><tr><th>成员</th><th>种植面积</th><th>预计产量</th><th>参保状态</th><th>保障数量</th><th>操作</th></tr></thead><tbody><tr v-for="m in memberRows" :key="m.id"><td>{{ m.name }}<small>{{ m.id }}</small></td><td>{{ number(m.area) }} 亩</td><td>{{ number(m.production) }} 吨</td><td>{{ scopePolicies.some(p=>p.memberId===m.id)?'已参保':'未参保' }}</td><td>{{ number(sum(scopePolicies.filter(p=>p.memberId===m.id).map(p=>p.tons))) }} 吨</td><td><button class="text-btn" @click="openRecord(m.id)">查看成员</button></td></tr><tr v-if="!memberRows.length"><td colspan="6">没有符合筛选条件的成员。</td></tr></tbody></table>
        <table v-else class="business-table"><thead><tr><th>项目 / 地区</th><th>农户覆盖</th><th>面积覆盖</th><th>补贴拨付</th><th>赔付兑现</th><th>操作</th></tr></thead><tbody><tr v-for="s in projectRows" :key="s.project.id"><td>{{ s.project.name }}<small>{{ s.project.region }} · {{ s.project.id }}</small></td><td>{{ s.insured.length }} / {{ s.project.targetHouseholds }} 户<small>{{ percent(s.insured.length,s.project.targetHouseholds) }}</small></td><td>{{ number(s.area) }} / {{ number(s.project.targetArea) }} 亩</td><td>{{ number(s.project.subsidyPaid) }} / {{ number(s.project.subsidyBudget) }} 元</td><td>{{ number(s.paid) }} / {{ number(s.due) }} 元</td><td><button class="text-btn" @click="openRecord(s.project.id)">查看项目</button></td></tr><tr v-if="!projectRows.length"><td colspan="6">没有符合筛选条件的项目。</td></tr></tbody></table>
      </div>
    </section>

    <section v-if="records && (detailPolicy||detailMember||detailProject)" ref="detailElement" tabindex="-1" class="panel detail-panel" aria-label="业务详情">
      <div class="panel-heading"><h2>{{ detailPolicy ? `保单详情 · ${detailPolicy.id}` : detailMember ? `成员详情 · ${detailMember.name}` : `项目详情 · ${detailProject?.project.name}` }}</h2><button class="select-btn" @click="selected=''">关闭详情</button></div>
      <template v-if="detailProject"><dl class="business-list"><div><dt>实施组织</dt><dd>{{ detailProject.project.cooperative }}</dd></div><div><dt>目标农户 / 已建档 / 已保障</dt><dd>{{ detailProject.project.targetHouseholds }} / {{ detailProject.members.length }} / {{ detailProject.insured.length }} 户</dd></div><div><dt>目标面积 / 已保障面积</dt><dd>{{ number(detailProject.project.targetArea) }} / {{ number(detailProject.area) }} 亩</dd></div><div><dt>补贴预算 / 已拨付</dt><dd>{{ number(detailProject.project.subsidyBudget) }} / {{ number(detailProject.project.subsidyPaid) }} 元</dd></div></dl><button v-if="role==='authority'&&detailProject.project.subsidyPaid<detailProject.project.subsidyBudget" class="primary-btn detail-action" @click="paySubsidy(detailProject.project.id)">模拟拨付剩余补贴</button></template>
      <template v-if="detailMember"><p class="business-note">成员编号 {{ detailMember.id }} · 种植 {{ number(detailMember.area) }} 亩 · 预计产量 {{ number(detailMember.production) }} 吨</p><button v-if="!detailPolicies.length" class="primary-btn" @click="enroll(detailMember.id)">建立模拟保单</button></template>
      <article v-for="p in detailPolicies" :key="p.id" class="policy-detail"><h3>{{ p.id }} · {{ business.members.find(m=>m.id===p.memberId)?.name }}</h3><dl class="business-list"><div><dt>保障数量 / 保障目标价</dt><dd>{{ number(p.tons) }} 吨 / {{ number(p.guarantee) }} 元/吨</dd></div><div><dt>免赔额 / 赔付上限</dt><dd>{{ number(p.deductible) }} 元/吨 / {{ number(p.cap) }} 元</dd></div><div><dt>合同约定结算期</dt><dd>{{ p.start }} 至 {{ p.end }}</dd></div><div><dt>结算价格</dt><dd>{{ p.status==='已结算'?`${number(p.settlement)} 元/吨`:'尚未到期结算' }}</dd></div><div><dt>结算应赔 / 理赔状态</dt><dd>{{ number(p.payout) }} 元 / {{ p.claim }}</dd></div></dl>
        <ol class="claim-steps" aria-label="理赔流程"><li v-for="(step,index) in ['未申请','待审核','待支付','已支付']" :key="step" :class="{done:index<=['未申请','待审核','待支付','已支付'].indexOf(p.claim)}">{{ step }}</li></ol>
        <div class="detail-buttons"><button v-if="role==='farmer'&&p.claim==='未申请'&&p.status==='已结算'&&p.payout>0" class="primary-btn" @click="act(p)">提交模拟理赔申请</button><button v-if="role==='insurer'&&p.claim==='待审核'" class="primary-btn" @click="act(p)">模拟审核通过</button><button v-if="role==='insurer'&&p.claim==='待支付'" class="primary-btn" @click="act(p)">模拟支付赔款</button><button v-if="role!=='authority'" class="select-btn" @click="emit('scenario',p)">带入保障试算</button></div>
        <p v-if="role === 'insurer'" class="business-note">合同资料待完善：缺少具体期货合约、采价字段、完整观察日和条款版本，暂不提供本保单模型预测。<button class="text-btn" @click="emit('comparison')">查看独立研究案例</button></p>
      </article>

    </section>
  </div>
</template>
