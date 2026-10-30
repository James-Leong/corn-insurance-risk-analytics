<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BusinessRecord, Column, SessionUser, Workspace } from './types'
import { fmt } from './labels'
import Icon from './Icon.vue'
import RecordTable from './RecordTable.vue'
import { downloadCsv } from './api'
const props=defineProps<{workspace:Workspace;page:string;user:SessionUser}>()
const emit=defineEmits<{action:[id:string,record?:BusinessRecord];select:[type:string,record:BusinessRecord];report:[]}>()
const cashPurpose=ref('claim')
const cashPurposes=[{value:'claim',label:'客户赔款'},{value:'all',label:'全部应付'},{value:'hedge_premium',label:'对冲权利金'},{value:'reinsurance_premium',label:'分保保费'},{value:'premium_refund',label:'保费退款'}]
const shownPayables=computed(()=>props.workspace.payables.filter(p=>cashPurpose.value==='all'||p.kind===cashPurpose.value))
const shownPayments=computed(()=>props.workspace.payments.filter(p=>cashPurpose.value==='all'||shownPayables.value.some(payable=>payable.id===p.payable_id)))
const approved=computed(()=>shownPayables.value.reduce((s,r)=>s+Number(r.amount||0),0))
const paid=computed(()=>shownPayables.value.reduce((s,r)=>s+Number(r.paid_amount||0),0))
const reserved=computed(()=>shownPayables.value.reduce((s,r)=>s+Number(r.reserved_amount||0),0))
const recoveryRemaining=computed(()=>props.workspace.recoveries.reduce((s,r)=>s+Math.max(0,Number(r.confirmed_amount||0)-Number(r.received_amount||0)),0))
const premiumAdjustments=computed(()=>(Array.isArray(props.workspace.premium_adjustments)?props.workspace.premium_adjustments:[]) as BusinessRecord[])
const fixingCols:Column[]=[{key:'id',label:'采价快照',secondary:'policy_id',width:'180px'},{key:'contract',label:'合约'},{key:'price_field',label:'价格字段'},{key:'expected_count',label:'应采点数',format:'number'},{key:'actual_count',label:'实采点数',format:'number'},{key:'average_price',label:'均价',format:'money'},{key:'status',label:'复核状态',format:'status'}]
const claimCols:Column[]=[{key:'id',label:'赔案编号',secondary:'policy_id',width:'180px'},{key:'rule_amount',label:'规则参考额',format:'money'},{key:'assessed_amount',label:'人工核定额',format:'money'},{key:'approved_amount',label:'批准累计额',format:'money'},{key:'status',label:'核赔状态',format:'status'}]
const payableCols:Column[]=[{key:'id',label:'应付事项',secondary:'source_id',width:'180px'},{key:'kind',label:'用途',format:'status'},{key:'counterparty',label:'收款相对方',width:'170px'},{key:'amount',label:'批准应付',format:'money'},{key:'paid_amount',label:'累计实付',format:'money'},{key:'reserved_amount',label:'已预占',format:'money'},{key:'balance',label:'未付余额',format:'money'},{key:'available_amount',label:'可付余额',format:'money'},{key:'status',label:'状态',format:'status'}]
const paymentCols:Column[]=[{key:'id',label:'付款请求',secondary:'payable_id',width:'180px'},{key:'kind',label:'付款用途',format:'status'},{key:'amount',label:'申请额',format:'money'},{key:'paid_amount',label:'已确认实付',format:'money'},{key:'reserved_amount',label:'在途/预占',format:'money'},{key:'status',label:'支付状态',format:'status'}]
const recoveryCols:Column[]=[{key:'id',label:'回收事项',secondary:'claim_id',width:'170px'},{key:'kind',label:'回收用途',format:'status'},{key:'expected_amount',label:'预计',format:'money'},{key:'confirmed_amount',label:'确认应收',format:'money'},{key:'received_amount',label:'累计实收',format:'money'},{key:'status',label:'回收状态',format:'status'}]
const recCols:Column[]=[{key:'id',label:'差异编号',secondary:'target_id',width:'170px'},{key:'type',label:'差异类型',format:'status'},{key:'description',label:'原始发现',width:'230px'},{key:'amount',label:'涉及金额',format:'money'},{key:'status',label:'处理状态',format:'status'}]
const premiumCols:Column[]=[{key:'id',label:'批改保费事项',secondary:'policy_id',width:'180px'},{key:'amount',label:'新增应收保费',format:'money'},{key:'received_amount',label:'已确认实收',format:'money'},{key:'status',label:'收款状态',format:'status'}]
const exportRows=(name:string,cols:Column[],records:BusinessRecord[])=>downloadCsv(name,cols,records)

</script>
<template>
 <template v-if="page==='fixings'">
  <div class="gg-context-strip"><span><Icon name="calendar" :size="17"/>合同观察日 · 逐日采价</span><p>缺失价格阻断核定，锁定快照保留来源和版本</p><button v-if="user.role==='operator'" class="gg-btn gg-btn-primary" @click="emit('action','fixing.prepare')"><Icon name="plus" :size="16"/>准备合同采价</button></div>
  <RecordTable title="采价快照与完整性" :records="workspace.fixings" :columns="fixingCols" empty="暂无采价记录；选择保单后生成约定观察日的完整性校验" @select="emit('select','fixing',$event)" @export="exportRows('采价快照',fixingCols,$event)"/>
  <div class="gg-subsection-heading"><div><h2>核赔与批准应付</h2><p>规则试算 → 人工核定 → 复核批准 → 应付事项</p></div><button v-if="user.role==='operator'" class="gg-btn" @click="emit('action','claim.calculate')">新建赔款核定<Icon name="arrow" :size="15"/></button></div>
  <RecordTable title="赔案核定台账" :records="workspace.claims" :columns="claimCols" @select="emit('select','claim',$event)" @export="exportRows('赔案核定',claimCols,$event)"/>
 </template>
 <template v-else-if="page==='cash'">
  <div class="gg-cash-purpose" role="group" aria-label="收付用途"><button v-for="purpose in cashPurposes" :key="purpose.value" :aria-pressed="cashPurpose===purpose.value" :class="{active:cashPurpose===purpose.value}" @click="cashPurpose=purpose.value">{{ purpose.label }}</button></div>
  <div class="gg-kpis"><article><span>{{ cashPurpose==='claim'?"批准客户赔款":"筛选内批准应付" }}<Icon name="file" :size="18"/></span><strong>{{ fmt(approved) }}<small>元</small></strong><p>{{ cashPurpose==='claim'?"客户赔款独立跟进，可切换其他用途":"当前用途合计，各项收付按用途独立记录" }}</p></article><article><span>已确认实付<Icon name="check" :size="18"/></span><strong>{{ fmt(paid) }}<small>元</small></strong><p>仅有效支付回执计入实付</p></article><article><span>在途与预占<Icon name="clock" :size="18"/></span><strong>{{ fmt(reserved) }}<small>元</small></strong><p>待审、处理中及未知状态继续占用</p></article><article class="gg-kpi-accent"><span>{{ "未付余额" }}<Icon name="settlement" :size="18"/></span><strong>{{ fmt(Math.max(0,approved-paid)) }}<small>元</small></strong><p>{{ "批准额减累计实付，含在途及预占" }}</p></article></div>
  <RecordTable :title="cashPurpose==='claim'?'客户赔款与到账余额':'批准应付与可付余额'" :records="shownPayables" :columns="payableCols" @select="emit('select','payable',$event)" @export="exportRows('应付明细',payableCols,$event)"/>
  <RecordTable title="付款申请与支付回执" :records="shownPayments" :columns="paymentCols" @select="emit('select','payment',$event)" @export="exportRows('付款回执',paymentCols,$event)"/>
  <RecordTable v-if="premiumAdjustments.length" title="批改新增保费与收款" :records="premiumAdjustments" :columns="premiumCols" @select="emit('select','premium_adjustment',$event)" @export="exportRows('批改保费收款',premiumCols,$event)"/>
  <div class="gg-subsection-heading"><div><h2>风险转移回收</h2><p>确认应收未到账 {{ fmt(recoveryRemaining) }} 元 · 与应付用途筛选独立，客户赔付不等待回款</p></div></div>
  <RecordTable title="再保摊回 / 对冲回款" :records="workspace.recoveries" :columns="recoveryCols" @select="emit('select','recovery',$event)" @export="exportRows('风险转移回收',recoveryCols,$event)"/>
 </template>
 <template v-else>
  <div class="gg-context-strip"><span><Icon name="link" :size="17"/>业务事实与资金逐项核对</span><p>保留差异原始发现与处置凭证，重复对账不重复记账</p><button v-if="user.role==='operator'" class="gg-btn gg-btn-primary" @click="emit('action','reconciliation.run')"><Icon name="refresh" :size="16"/>执行项目对账</button></div>
  <RecordTable title="对账差异与处理" :records="workspace.reconciliations" :columns="recCols" empty="暂无对账差异；可执行项目对账校验实际未结事项" @select="emit('select','reconciliation',$event)" @export="exportRows('对账差异',recCols,$event)"/>
  <section class="gg-card gg-closeout"><div class="gg-closeout-icon"><Icon name="file" :size="33"/></div><div><span class="gg-overline">项目全链档案</span><h2>项目报告与结案核验</h2><p>同一版本汇总申请、保单、研究依据、风险转移、核赔及收付。未结事项逐项保留，不以报告生成替代业务结清。</p><div class="gg-inline-actions"><button class="gg-btn" @click="emit('report')"><Icon name="download" :size="16"/>导出项目档案</button><button v-if="user.role==='reviewer' && workspace.projects[0]" class="gg-btn gg-btn-primary" @click="emit('action','project.close',workspace.projects[0])">提交结案核验<Icon name="arrow" :size="15"/></button></div></div></section>
 </template>
</template>
