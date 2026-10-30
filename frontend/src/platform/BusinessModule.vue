<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BusinessRecord, Column, SessionUser, Workspace } from './types'
import { auditLabel, date, fmt, label, tone } from './labels'
import Icon from './Icon.vue'
import RecordTable from './RecordTable.vue'
import { downloadCsv } from './api'
const props=defineProps<{workspace:Workspace;page:string;user:SessionUser}>()
const emit=defineEmits<{action:[id:string,record?:BusinessRecord];select:[type:string,record:BusinessRecord];navigate:[page:string];task:[record:BusinessRecord];import:[]}>()
const applications=computed(()=>props.workspace.applications||[])
const policies=computed(()=>props.workspace.policies||[])
const active=computed(()=>policies.value.filter(r=>r.status==='active'))
const tons=computed(()=>active.value.reduce((s,r)=>s+Number(r.tons||0),0))
const outstanding=computed(()=>applications.value.filter(r=>!['rejected','withdrawn'].includes(r.status)).reduce((s,r)=>s+Math.max(0,Number(r.premium_due||0)-Number(r.premium_received||0)),0))
const tasks=computed(()=>(props.workspace.tasks||[]).filter(r=>!['done','resolved','closed'].includes(r.status)))
const showAllTasks=ref(false)
const appCols:Column[]=[{key:'id',label:'申请编号',secondary:'created_at',width:'160px'},{key:'insured_name',label:'被保险人',secondary:'region'},{key:'tons',label:'保障数量',format:'tons'},{key:'premium_due',label:'应收保费',format:'money'},{key:'premium_received',label:'已收保费',format:'money'},{key:'status',label:'办理状态',format:'status'}]
const policyCols:Column[]=[{key:'policy_no',label:'保单号',secondary:'id',width:'180px'},{key:'insured_name',label:'被保险人',secondary:'region'},{key:'tons',label:'有效数量',format:'tons'},{key:'guarantee_price',label:'保障价格',format:'money'},{key:'period_end',label:'保险止期',format:'date'},{key:'version',label:'责任版本'},{key:'status',label:'保单状态',format:'status'}]
const myClaims=computed(()=>(props.workspace.claims||[]).map(claim=>({...claim,
 policy_no:policies.value.find(policy=>policy.id===claim.policy_id)?.policy_no||claim.policy_id,
 payment_status_label:({not_payable:'待核定或尚未形成应付',zero_closed:'零赔结案',payable:'批准待付',processing:'付款办理中',unknown:'付款待核实',partially_paid:'部分到账',paid:'已全部到账'}as Record<string,string>)[String(claim.payment_status)]||label(claim.status),
})))
const myClaimCols:Column[]=[{key:'id',label:'赔付事项',secondary:'policy_no',width:'180px'},
 {key:'approved_amount',label:'批准赔款',format:'money'},{key:'paid_amount',label:'已到账',format:'money'},
 {key:'unpaid_amount',label:'尚未到账',format:'money'},{key:'payment_status_label',label:'办理进度'},
 {key:'notification_status',label:'通知状态',format:'status'}]
const exportRows=(name:string,cols:Column[],rows:BusinessRecord[])=>downloadCsv(name,cols,rows)
const progress=computed(()=>[
 {title:'接收申请',count:applications.value.length,note:'保留逐户资料与责任',page:'applications'},
 {title:'核保审核',count:applications.value.filter(r=>['submitted','approved','issuing','issued'].includes(r.status)).length,note:'批准版本进入后续流程',page:'applications'},
 {title:'承保出单',count:policies.value.length,note:'确认回执形成保单',page:'policies'},
 {title:'风险转移',count:(props.workspace.hedges||[]).length,note:'仅确认量形成合同',page:'portfolio'},
 {title:'到期赔付',count:(props.workspace.claims||[]).length,note:'核定、应付和实付分列',page:'fixings'},
])
</script>
<template>
  <template v-if="page==='overview'">
    <div class="gg-kpis">
      <article><span>有效承保责任<Icon name="policy" :size="18"/></span><strong>{{ fmt(tons) }}<small>吨</small></strong><p>{{ active.length }} 份有效保单 · 责任版本可追溯</p></article>
      <article><span>本批投保申请<Icon name="file" :size="18"/></span><strong>{{ applications.length }}<small>户</small></strong><p><b>{{ applications.filter(r=>r.status==='submitted').length }}</b> 户待核保 · {{ applications.filter(r=>r.status==='needs_materials').length }} 户待补件</p></article>
      <article><span>保费待收余额<Icon name="settlement" :size="18"/></span><strong>{{ fmt(outstanding) }}<small>元</small></strong><p>基于申请应收与已确认实收</p></article>
      <article class="gg-kpi-accent"><span>当前未结待办<Icon name="clock" :size="18"/></span><strong>{{ tasks.length }}<small>项</small></strong><p>业务状态驱动 · 点击待办直接办理</p></article>
    </div>
    <section class="gg-card gg-flow-card"><div class="gg-card-heading"><div><h2>一批业务，一条办理主线</h2><p>投保、研究、风险转移与赔付共享项目及业务编号</p></div><span class="gg-chip">本期合同范围</span></div><div class="gg-process"><button v-for="(step,i) in progress" :key="step.title" @click="emit('navigate',step.page)"><span class="gg-step-index">0{{ i+1 }}</span><strong>{{ step.title }}<b>{{ step.count }}</b></strong><small>{{ step.note }}</small><Icon v-if="i<progress.length-1" name="arrow" :size="16" class="gg-flow-arrow"/></button></div></section>
    <div class="gg-two-columns gg-overview-columns"><section class="gg-card"><div class="gg-card-heading"><div><h2>团队待办<span class="gg-counter">{{ tasks.length }}</span></h2><p>处理来源事项后自动更新，已读不会关闭待办</p></div><span class="gg-live-label"><i/>实时业务快照</span></div><div v-if="!tasks.length" class="gg-empty"><Icon name="check" :size="30"/><strong>当前暂无待办</strong><span>新申请、待确认交易与待付款会在这里出现。</span></div><button v-for="task in tasks.slice(0,showAllTasks?tasks.length:6)" :key="task.id" class="gg-task" @click="emit('task',task)"><span class="gg-task-icon"><Icon :name="String(task.module||'policy').includes('payment')?'settlement':'file'" :size="18"/></span><div><strong>{{ task.title || task.name || task.message || '待办事项' }}</strong><small>{{ task.source_id || task.target_id || task.entity_id || task.id }} · {{ label(task.status) }}</small></div><span class="gg-badge" :class="`gg-${tone(task.priority||task.status)}`">{{ label(task.priority||task.status) }}</span><Icon name="chevron" :size="15"/></button><button v-if="tasks.length>6" class="gg-text-btn gg-full-link" @click="showAllTasks=!showAllTasks">{{ showAllTasks?'收起更多待办':'展开全部待办' }}<Icon name="arrow" :size="14"/></button></section>
      <section class="gg-card"><div class="gg-card-heading"><div><h2>项目与产品档案</h2><p>承保使用批准产品，固定规则只读</p></div><Icon name="risk" :size="20"/></div><div class="gg-project-badge"><span class="gg-product-icon"><Icon name="grain" :size="28"/></span><div><strong>{{ workspace.product.name || '玉米价格保险' }}</strong><small>产品条款 · v{{ workspace.product.version }}</small></div><span class="gg-badge gg-warning">产品版本</span></div><dl class="gg-facts"><div><dt>保障价格</dt><dd>{{ fmt(workspace.product.guarantee_price) }} 元/吨</dd></div><div><dt>指定合约</dt><dd>{{ workspace.product.contract || workspace.product.ticker || '以保单快照为准' }}</dd></div><div><dt>采价规则</dt><dd>{{ label(workspace.product.fixing_method || workspace.product.price_field) }} · {{ label(workspace.product.price_field) }}</dd></div><div><dt>数据快照</dt><dd>{{ date(workspace.as_of) }}</dd></div><div><dt>执行通道</dt><dd>保险核心 · 场外期权 · 支付</dd></div></dl><div class="gg-note"><Icon name="info" :size="16"/><span>各项办理以当前批准条款和责任版本为依据，保留关联业务及办理记录。</span></div></section>
    </div>
    <section class="gg-card gg-audit"><div class="gg-card-heading"><div><h2>最近业务记录</h2><p>记录跨模块操作、当前版本与办理人员</p></div><span class="gg-chip">版本 {{ workspace.revision }}</span></div><div v-if="!workspace.audit_events?.length" class="gg-empty gg-small-empty">暂无操作记录</div><div v-for="event in (workspace.audit_events||[]).slice(-4).reverse()" :key="event.id" class="gg-audit-row"><i/><span>{{ auditLabel(event.command || event.action) }}</span><small>{{ event.actor_name || event.actor_id || '系统' }}</small><time>{{ date(event.created_at) }}</time></div></section>
  </template>
  <template v-else-if="page==='applications'">
    <div class="gg-context-strip"><span><Icon name="building" :size="17"/>逐户申请 · 服务端保存</span><p>草稿 → 提交审核 → 保费确认 → 出单请求 → 权威回执</p><div v-if="user.role==='operator'||user.role==='customer'"><button class="gg-btn" @click="emit('import')"><Icon name="upload" :size="16"/>批量导入</button><button class="gg-btn gg-btn-primary" @click="emit('action','application.create')"><Icon name="plus" :size="16"/>新建投保申请</button></div></div>
    <RecordTable title="投保申请台账" :records="applications" :columns="appCols" @select="emit('select','application',$event)" @export="exportRows('投保申请',appCols,$event)"/>
    <section v-if="Array.isArray(workspace.batches)&&workspace.batches.length" class="gg-card"><div class="gg-card-heading"><div><h2>导入批次</h2><p>预览不生成保单，通过后逐户创建申请草稿</p></div></div><div v-for="batch in (workspace.batches as BusinessRecord[])" :key="batch.id" class="gg-audit-row"><Icon name="upload" :size="16"/><button class="gg-text-btn" @click="emit('select','batch',batch)">{{ batch.id }}</button><span class="gg-badge" :class="`gg-${tone(batch.status)}`">{{ label(batch.status) }}</span><span>{{ batch.valid_count || batch.row_count || 0 }} 行</span><time>{{ date(batch.created_at) }}</time></div></section>
  </template>
  <template v-else>
    <div class="gg-mini-summary"><span><i class="gg-dot"/>有效保单 <b>{{ active.length }}</b> 份</span><span>有效保障数量 <b>{{ fmt(tons) }}</b> 吨</span><span>产品版本和保单责任独立留存</span></div>
    <section v-if="user.role==='customer'" class="gg-card"><div class="gg-card-heading"><div><h2>我的赔付进度</h2><p>仅展示本人或本账号授权保单的赔付结果，到账以有效支付回执为准。</p></div><Icon name="settlement" :size="20"/></div><div class="gg-note"><Icon name="info" :size="16"/><span>当前为付款进度；天气、土壤及倒伏提示仅供风险判断，赔款按本保单约定的价格规则核定。</span></div></section>
    <RecordTable v-if="user.role==='customer'" title="我的赔付明细" :records="myClaims" :columns="myClaimCols" empty="暂无赔付事项；到期核定后，可在这里查看批准赔款、支付进度及到账结果。" @select="emit('select','claim',$event)" @export="exportRows('我的赔付进度',myClaimCols,$event)"/>
    <RecordTable title="保单责任档案" :records="policies" :columns="policyCols" empty="暂无已确认保单，申请审核及出单查回后将在此形成记录" @select="emit('select','policy',$event)" @export="exportRows('保单档案',policyCols,$event)"/>
    <div class="gg-inline-help"><Icon name="info" :size="17"/><p>从保单详情查看条款快照、再保和对冲关联、采价与赔案。有效条款的变更通过批改办理，并保留历史责任版本。</p></div>
  </template>
</template>
