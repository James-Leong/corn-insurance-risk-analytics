import type { BusinessRecord, CommandForm, FormField, Workspace } from './types'
import { fmt, label } from './labels'
const field = (key:string,label:string,value:unknown='',type:FormField['type']='text',help?:string):FormField => ({key,label,value,type,required:true,help})
const reason = (value='') => field('reason','办理依据与说明',value,'textarea')
const select = (key:string,name:string,records:BusinessRecord[],title=(r:BusinessRecord)=>String(r.name || r.policy_no || r.id)):FormField => ({key,label:name,type:'select',required:true,options:records.map(r=>({value:r.id,label:title(r)})),value:records[0]?.id || ''})
const ref = () => field('reference','外部凭证或业务参考号',`GG-${new Date().toISOString().slice(0,10).replaceAll('-','')}-${Math.random().toString(36).slice(2,7).toUpperCase()}`)
const decision = (options:string[]) => ({key:'decision',label:'复核结论',type:'select' as const,required:true,value:options[0],options:options.map(s=>({value:s,label:label(s)}))})
export type UiAction = { id:string; label:string; primary?:boolean }
export function actions(type:string,record:BusinessRecord,role:string):UiAction[] {
 const s=record.status, operator=role==='operator', reviewer=role==='reviewer', customer=role==='customer'
 const result:UiAction[]=[]; const add=(id:string,text:string,primary=false)=>result.push({id,label:text,primary})
 if(type==='application'){
  if((operator||customer)&&['draft','needs_materials','rejected'].includes(s))add('application.update','修改 / 补件')
  if((operator||customer)&&['draft','needs_materials'].includes(s))add('application.submit','提交审核',true)
  if((operator||customer)&&['draft','needs_materials','submitted','approved','rejected'].includes(s)&&!Number(record.premium_received||0))add('application.withdraw','撤回本申请')
  if(reviewer&&s==='submitted') add('application.review','审核申请',true)
  if(operator&&s==='approved'&&Number(record.premium_received||0)<Number(record.premium_due||0)) add('application.premium','登记保费回执')
  if(operator&&s==='approved'&&Number(record.premium_received||0)>=Number(record.premium_due||0))add('policy.issue','提交出单',true)
  if(operator&&s==='issuing')add('policy.query','查询出单结果',true)
 }
 if(type==='policy') {if(operator&&s==='active'&&!record.pending_change)add('policy.change','申请批改 / 退保');if(reviewer&&record.pending_change)add('policy.change.review','复核保单变更',true);if(operator&&s==='active'&&!record.pending_change)add('fixing.prepare','准备合同采价')}
 if(type==='premium_adjustment'&&operator&&s==='pending_confirmation')add('premium.adjustment_confirm','确认批改保费到账',true)
 if(type==='allocation'&&reviewer&&s==='needs_review'){add('hedge.allocation.reconfirm','复核并重新匹配',true);add('hedge.allocation.release','批准释放匹配')}
 if(type==='reinsurance_allocation'&&reviewer&&s==='needs_review'){add('reinsurance.allocation.reconfirm','复核再保适用',true);add('reinsurance.allocation.close','停止新增适用')}
 if(type==='reinsurance'&&reviewer)add('reinsurance.allocate','关联保单责任',true)
 if(type==='plan'){
  if(operator&&['draft','quoted','approved','rejected','invalidated'].includes(s)){add('hedge.update','修改方案');add('hedge.quote','登记报价')}
  if(reviewer&&s==='quoted')add('hedge.review','复核风险方案',true)
  if(operator&&s==='approved')add('hedge.submit','提交对冲交易',true)
 }
 if(type==='execution'){if(operator&&['processing','unknown','partially_confirmed'].includes(s))add('hedge.query','查询执行结果');if(reviewer&&['processing','unknown','partially_confirmed'].includes(s))add('hedge.confirm','登记成交确认',true)}
 if(type==='hedge'&&operator)add('hedge.allocate','匹配保单责任',true)
 if(type==='fixing'){if(reviewer&&s==='pending_review')add('fixing.confirm','复核并锁定采价',true);if(operator&&s==='locked')add('claim.calculate','计算并提交核定',true)}
 if(type==='claim'){if(reviewer&&s==='pending_review')add('claim.review','复核赔款核定',true);if(operator&&s==='rejected')add('claim.correct','修改并重新提交',true);if(operator&&['payable','partially_paid','paid','zero_closed'].includes(s))add('claim.correct','提交差额更正')}
 if(type==='payable'&&operator&&Number(record.available_amount??Math.max(0,Number(record.amount||0)-Number(record.paid_amount||0)-Number(record.reserved_amount||0)))>0)add('payment.create','申请付款',true)
 if(type==='payment'){if(reviewer&&s==='pending_review')add('payment.review','复核并发送',true);if(operator&&['processing','unknown','partially_paid'].includes(s))add('payment.receipt','登记支付回执',true)}
 if(type==='recovery'){if(reviewer&&s==='expected')add('recovery.confirm','确认应收',true);if(operator&&['confirmed','partially_received'].includes(s))add('recovery.receipt','登记本次回款',true)}
 if(type==='reconciliation'&&reviewer&&s!=='resolved')add('reconciliation.resolve','复核差异处置',true)
 if(type==='batch'&&(operator||customer)&&s==='valid')add('application.import_confirm','确认导入逐户申请',true)
 if(type==='project'&&reviewer&&s!=='closed')add('project.close','确认项目结案',true)
 return result
}
export function commandForm(id:string,ws:Workspace,r?:BusinessRecord):CommandForm {
 const activePolicies=ws.policies.filter(p=>p.status==='active'&&!p.pending_change)
 const base:CommandForm={command:id,title:'办理业务',description:'操作由服务端校验项目授权、业务状态及当前版本。',target:r,fields:[],note:'当前为业务办理通道。确认和回执不会向真实保险、交易或支付系统发送指令。'}
 const appFields = [field('applicant_name','投保人',r?.applicant_name||''),field('insured_name','被保险人',r?.insured_name||''),field('tons','保障数量（吨）',r?.tons||100,'number'),field('area_mu','种植面积（亩）',r?.area_mu||200,'number'),field('region','标的区域',r?.region||'黑龙江省绥化市'),field('phone','联系电话',r?.phone||''),field('period_start','保险起期',r?.period_start||'2026-10-01','date'),field('period_end','保险止期',r?.period_end||'2027-01-15','date'),field('materials_text','材料名称',Array.isArray(r?.materials)?r.materials.join('、'):'种植证明、身份材料','text','以顿号分隔材料名称；本期登记材料清单。'),{key:'terms_confirmed',label:'条款确认',type:'checkbox' as const,required:true,value:r?.terms_confirmed || false,help:'已阅读并同意本项目批准产品条款及投保声明'}]
 const appMap=(v:Record<string,unknown>)=>{const {materials_text,...rest}=v;return {...rest,materials:String(materials_text||'').split(/[、,，]/).map(x=>x.trim()).filter(Boolean)}}
 switch(id){
 case'decision.record':return{...base,target:undefined,title:'记录人工承保判断',description:'根据当前查看的数据及区域情况记录人工意见；该记录不能替代核保审批，也不会自动修改价格险赔付规则。',fields:[field('region','判断适用地区',r?.region||'黑龙江省绥化市'),{key:'disposition',label:'人工判断',type:'select',required:true,value:'review',options:[{value:'proceed',label:'继续办理投保'},{value:'hold',label:'暂缓办理'},{value:'review',label:'补充资料或进一步复核'}]},reason()],map:v=>({...v,...(r?.source_context?{source_context:r.source_context}:{})}),submitLabel:'保存只读判断记录'}
 case'application.create':return{...base,target:undefined,title:'新建投保申请',description:`产品参数由批准版本读取，保存草稿后可提交审核。保障价格：${fmt(ws.product.guarantee_price)} 元/吨。`,fields:[...appFields,...(r?.decision_id?[{...field('decision_id','关联人工判断编号',r.decision_id),readonly:true,required:false}]:[])],map:appMap,submitLabel:'保存申请草稿'}
 case'application.update':return{...base,title:'修改申请 / 补充资料',description:'关键要素变更将使原审核失效，需重新提交复核。',fields:appFields,map:appMap}
 case'application.submit':return{...base,title:'提交投保审核',description:'请核对投保人、保障数量、期间及材料；提交后进入复核待办。',fields:[{key:'terms_confirmed',label:'投保确认',type:'checkbox',required:true,value:false,help:'已确认当前申请资料与产品条款，提交本版本审核'}],submitLabel:'提交审核'}
 case'application.withdraw':return{...base,title:'撤回未办投保申请',description:'仅撤回尚未出单且未收保费的申请，保留原申请及办理记录。',fields:[reason()],submitLabel:'确认撤回申请'}
 case'application.review':return{...base,title:'投保申请审核',description:'复核当前申请版本，待补件和拒绝须留下明确原因。',fields:[decision(['approved','needs_materials','rejected']),reason()],submitLabel:'确认审核结论'}
 case'application.premium':return{...base,title:'登记保费回执',description:'登记已经确认的本次保费收款；允许部分缴费，实收不足时仍保留未收余额。',fields:[field('amount','本次实收（元）',Math.max(0,Number(r?.premium_due||0)-Number(r?.premium_received||0)),'number'),ref()]}
 case'policy.issue':return{...base,title:'提交出单请求',description:'将已审核申请提交保险核心。请求受理后还需查单确认，才会生成有效保单。',fields:[{key:'ack',label:'出单确认',type:'checkbox',required:true,help:'已核对保费前置条件与本次申请版本'}],map:()=>({}),submitLabel:'提交出单请求'}
 case'policy.query':return{...base,title:'查询出单结果',description:'查回原请求，重复查询不会生成第二张保单。',fields:[{key:'outcome',label:'出单查询结果',type:'select',value:'confirmed',required:true,options:[{value:'confirmed',label:'确认出单'},{value:'unknown',label:'结果未知，继续等待'},{value:'failed',label:'确认出单失败'}]}]}
 case'policy.change':return{...base,title:'申请保单批改 / 退保',description:'有效保单不直接编辑。批准后生成责任版本，并提示关联风险分配复核。',fields:[field('tons','批改后保障数量（吨）',r?.tons,'number'),{key:'terminate',label:'退保申请',type:'checkbox',value:false,help:'勾选则申请终止责任；不删除历史记录'},reason()]}
 case'policy.change.review':return{...base,command:'policy.change',title:'复核保单变更',description:'核对变更及其对责任匹配和收付事项的影响。',fields:[{key:'action',label:'复核结论',type:'select',required:true,value:'approve',options:[{value:'approve',label:'批准变更'},{value:'reject',label:'退回变更'}]},reason()]}
 case'premium.adjustment_confirm':return{...base,title:'确认批改新增保费',description:'依据批准批改登记本次实际收款；允许部分缴费，未足额前继续保留待办。',fields:[field('amount','本次实收保费（元）',Math.max(0,Number(r?.amount||0)-Number(r?.received_amount||0)),'number'),ref()]}
 case'reinsurance.allocate':return{...base,title:'关联既有再保安排',description:'仅确认适用的已接受安排计入分出；分保与衍生品对冲分别记录。',fields:[select('policy_id','适用保单',activePolicies),{...field('ratio','本保单分出比例',r?.ratio||.3,'number','0～1，例如0.3表示30%'),max:1},ref()]}
 case'reinsurance.allocation.reconfirm':return{...base,command:'reinsurance.allocate',target:ws.reinsurance.find(x=>x.id===r?.arrangement_id),title:'复核批改后的再保适用',description:'按当前保单责任重新确认已有再保分配，保留历史分配及分保保费调整记录。',fields:[{...select('policy_id','当前保单责任',activePolicies),value:r?.policy_id,readonly:true},{...field('ratio','合同分出比例',r?.ratio||.3,'number'),readonly:true},ref()]}
 case'reinsurance.allocation.close':return{...base,command:'reinsurance.allocate',target:ws.reinsurance.find(x=>x.id===r?.arrangement_id),title:'停止再保分配新增适用',description:'保留历史归属和已发生的收付事实；该分配不再计入当前新增责任。',fields:[reason()],map:v=>({...v,allocation_id:r?.id,action:'close_for_new'})}
 case'hedge.plan':return{...base,title:'新建对冲方案',description:'首期采用场外看跌期权路线。引用有效责任和只读研究依据，不自动发交易。',fields:[field('name','方案名称','玉米价格风险转移方案'),select('policy_id','责任保单',activePolicies),field('tons','名义数量（吨）',100,'number'),field('strike_price','执行价格（元/吨）',ws.product.guarantee_price||2400,'number'),field('premium_per_ton','权利金预算（元/吨）',40,'number'),{...field('report_id','研究报告编号（可选）'),required:false},reason()],map:v=>{const{policy_id,...rest}=v;return{...rest,policy_ids:[policy_id],tool:'otc_put'}}}
 case'hedge.update':return{...base,title:'修改对冲方案',description:'数量、执行价格及费用等实质要素修改后，旧审批失效。',fields:[field('tons','名义数量（吨）',r?.tons,'number'),field('strike_price','执行价格（元/吨）',r?.strike_price,'number'),field('premium_per_ton','权利金预算（元/吨）',r?.premium_per_ton,'number'),reason()]}
 case'hedge.quote':return{...base,title:'登记场外报价',description:'报价仅用于方案比较和审批，不形成成交或持仓。报价默认30分钟有效。',fields:[field('premium_per_ton','报价权利金（元/吨）',r?.premium_per_ton||40,'number'),ref()]}
 case'hedge.review':return{...base,title:'复核风险转移方案',description:'审批绑定当前责任、方案及报价版本，后续实质变更需重新复核。',fields:[decision(['approved','rejected']),reason()]}
 case'hedge.submit':return{...base,title:'提交对冲交易',description:'服务端预占责任、数量及预算，提交受理后进入执行队列；以实际成交确认计入合同。',fields:[{key:'ack',label:'交易确认',type:'checkbox',required:true,value:false,help:'已核对有效报价、审批版本和交易要素'}],map:()=>({}),submitLabel:'提交委托'}
 case'hedge.confirm':return{...base,title:'登记分批成交确认',description:'填写累计已确认数量。最终确认仅释放未成交余量，既有确认不会被删除。',fields:[field('cumulative_tons','累计成交确认量（吨）',r?.confirmed_tons||r?.requested_tons,'number'),field('event_id','确认事件号',`GG-CONF-${crypto.randomUUID().slice(0,8)}`),{key:'final',label:'最终确认',type:'checkbox',value:false,help:'本次为最终确认，剩余未成交量结束预占'}]}
 case'hedge.query':return{...base,title:'查询交易执行结果',description:'结果未知时继续保留预占，不另发新交易；按原请求跟进查询与异常处置。',fields:[{key:'outcome',label:'查询回报',type:'select',value:'unknown',required:true,options:[{value:'unknown',label:'结果未知，保持预占'},{value:'confirmed',label:'确认成交'},{value:'rejected',label:'明确拒绝'}]},{...field('cumulative_tons','累计确认量（吨）',r?.confirmed_tons||0,'number'),required:false}]}
 case'hedge.allocate':return{...base,title:'匹配对冲合同与保单',description:'按实际确认数量匹配，服务端同时校验保单和合同剩余量。名义匹配不代表风险完全消除。',fields:[select('policy_id','保单责任',activePolicies.filter(p=>!Array.isArray(r?.policy_ids)||(r?.policy_ids as unknown[]).includes(p.id))),field('tons','本次匹配数量（吨）',Math.max(0,Number(r?.tons||0)-ws.allocations.filter(a=>a.hedge_id===r?.id&&['confirmed','needs_review'].includes(a.status)).reduce((s,a)=>s+Number(a.tons||0),0)),'number')]}
 case'hedge.allocation.reconfirm':return{...base,command:'hedge.allocate',target:ws.hedges.find(x=>x.id===r?.hedge_id),title:'复核批改后的责任匹配',description:'核对当前责任版本，按双方可分配数量重新确认；原分配数量和版本保留历史。',fields:[field('tons','复核后匹配数量（吨）',r?.tons||0,'number'),reason()],map:v=>({...v,allocation_id:r?.id,action:'reconfirm'})}
 case'hedge.allocation.release':return{...base,command:'hedge.allocate',target:ws.hedges.find(x=>x.id===r?.hedge_id),title:'批准释放原责任匹配',description:'释放原保单与合同的匹配关系，不删除已确认成交、付款及历史分配事实。',fields:[reason()],map:v=>({...v,allocation_id:r?.id,action:'release'})}
 case'fixing.prepare':return{...base,title:'准备合同采价',description:'根据本保单采价规则读取具体合约的实际观测。数据缺失时阻止核定，不使用预测值替代。',target:undefined,fields:[{...select('policy_id','采价保单',activePolicies),value:r?.id||activePolicies[0]?.id}],submitLabel:'校验并生成采价快照'}
 case'fixing.confirm':return{...base,title:'复核并锁定采价',description:'请确认逐日价格、字段、单位和观察窗口。锁定快照后，上游修订不会静默覆盖核赔依据。',fields:[reason()],submitLabel:'批准锁定采价'}
 case'claim.calculate':return{...base,title:'规则计算与赔款核定',description:'根据已锁定采价及保单版本计算规则参考额；提交后等待复核，尚不生成有效应付。',target:undefined,fields:[{...select('policy_id','责任保单',ws.policies),value:r?.policy_id||ws.policies[0]?.id},{...select('fixing_id','锁定采价快照',ws.fixings.filter(x=>x.status==='locked')),value:r?.id||ws.fixings.find(x=>x.status==='locked')?.id},{...field('assessed_amount','人工核定金额（元，可选）','','number','留空则采用规则参考额。与规则不一致须填写依据。'),required:false},{...reason(),required:false}],map:v=>Object.fromEntries(Object.entries(v).filter(([k,val])=>k!=='assessed_amount'||val!==''))}
 case'claim.review':return{...base,title:'复核赔款核定',description:'批准正赔才生成应付；批准零赔独立结案。保险赔付不等待再保或对冲回款。',fields:[decision(['approved','rejected']),field('approved_amount','批准金额（元）',r?.assessed_amount??r?.rule_amount??0,'number'),reason()]}
 case'claim.correct':return{...base,title:r?.status==='rejected'?'修改并重新提交赔款核定':'提交赔款差额更正',description:r?.status==='rejected'?'根据退回意见修改核定金额与依据，保留原核定记录并重新提交独立复核。':'更正保留原核定和已付事实，重新批准后仅生成差额应付。',fields:[field('assessed_amount','更正后累计核定额（元）',r?.status==='rejected'?(r.assessed_amount??0):(r?.approved_amount??r?.assessed_amount??0),'number'),reason()]}
 case'payment.create':return{...base,title:'申请本次付款',description:`用途：${label(r?.kind)}。提交立即预占可付余额；待审、处理中及待核实持续占用，部分付款保留余额。`,fields:[field('amount','本次申请金额（元）',r?.available_amount??Math.max(0,Number(r?.amount||0)-Number(r?.paid_amount||0)-Number(r?.reserved_amount||0)),'number'),ref()]}
 case'payment.review':return{...base,title:'复核并发送付款',description:'审批通过后进入支付通道，尚未收到成功回执前不记实付。',fields:[decision(['approved','rejected']),reason()]}
 case'payment.receipt':return{...base,title:'登记支付回执',description:'支付回执按事件号去重，累计实付不超过本次申请金额。未知结果保留在途占用。',fields:[{key:'outcome',label:'回执状态',type:'select',required:true,value:'unknown',options:[{value:'unknown',label:'结果未知，待核实'},{value:'success',label:'成功到账'},{value:'partial',label:'部分支付'},{value:'failed',label:'明确失败，释放未付余量'}]},field('cumulative_amount','本申请累计实付（元）',r?.paid_amount||0,'number',`未知时保持已确认的 ${fmt(r?.paid_amount||0)} 元；成功时须填写全额 ${fmt(r?.amount||0)} 元。`),field('event_id','支付事件号',`GG-PAY-${crypto.randomUUID().slice(0,8)}`),ref()]}
 case'recovery.confirm':return{...base,title:'确认风险转移应收',description:'区分预计、确认应收和实收。再保摊回与对冲结算分别核对，不抵销客户应赔。',fields:[field('amount','确认应收（元）',r?.expected_amount||0,'number'),ref()]}
 case'recovery.receipt':return{...base,title:'登记本次回款',description:'仅将本次实际到账匹配到当前应收；部分回款继续保留未收余额。',fields:[field('amount','本次到账金额（元）',Math.max(0,Number(r?.confirmed_amount||0)-Number(r?.received_amount||0)),'number'),field('event_id','回款事件号',`GG-REC-${crypto.randomUUID().slice(0,8)}`),ref()]}
 case'reconciliation.run':return{...base,target:undefined,title:'执行项目对账',description:'按当前服务端事实核对责任、交易、核赔及资金。相同未结事项关联原差异，不重复记账。',fields:[],submitLabel:'执行对账'}
 case'reconciliation.resolve':return{...base,title:'复核差异处置',description:'保留原始发现、处理依据和凭证；处置确认不会修改或抹去正式业务事实。',fields:[reason(),ref()]}
 case'project.close':return{...base,title:'确认项目结案',description:'服务端核对未结责任、支付及回收；存在未结事项将阻止最终结案并显示原因。',fields:[reason()],submitLabel:'提交结案核验'}
 default:return base
 }
}
