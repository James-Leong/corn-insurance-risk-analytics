import { reactive, watch } from 'vue'

export interface Project {
  id: string; name: string; region: string; cooperative: string; targetHouseholds: number; targetArea: number
  subsidyBudget: number; subsidyPaid: number; premium: number; hedgeCost: number; hedgeValue: number
}
export interface Member { id: string; name: string; projectId: string; area: number; production: number }
export interface Policy {
  id: string; memberId: string; projectId: string; area: number; tons: number; guarantee: number; deductible: number; cap: number
  start: string; end: string; status: '保障中' | '已结算'; settlement: number; claim: '未申请' | '待审核' | '待支付' | '已支付'; payout: number
}
interface Store { projects: Project[]; members: Member[]; policies: Policy[] }
export const demoDate = '2026-10-18'
const key = 'grainguard-business-demo-v1'
function seed(): Store {
  const projects: Project[] = [
    { id:'PRJ-001',name:'示范项目 A',region:'示范区 A',cooperative:'示范合作社 A',targetHouseholds:5,targetArea:1800,subsidyBudget:80000,subsidyPaid:60000,premium:120000,hedgeCost:84000,hedgeValue:108000 },
    { id:'PRJ-002',name:'示范项目 B',region:'示范区 B',cooperative:'示范合作社 B',targetHouseholds:4,targetArea:1500,subsidyBudget:65000,subsidyPaid:25000,premium:96000,hedgeCost:66000,hedgeValue:75000 },
    { id:'PRJ-003',name:'示范项目 C',region:'示范区 C',cooperative:'示范合作社 C',targetHouseholds:4,targetArea:1600,subsidyBudget:70000,subsidyPaid:70000,premium:108000,hedgeCost:78000,hedgeValue:90000 },
  ]
  const members: Member[] = [
    {id:'F001',name:'演示农户 001',projectId:'PRJ-001',area:300,production:180},
    {id:'F002',name:'演示农户 002',projectId:'PRJ-001',area:450,production:270},
    {id:'F003',name:'演示农户 003',projectId:'PRJ-001',area:380,production:228},
    {id:'F004',name:'演示农户 004',projectId:'PRJ-001',area:320,production:192},
    {id:'F005',name:'演示农户 005',projectId:'PRJ-002',area:400,production:240},
    {id:'F006',name:'演示农户 006',projectId:'PRJ-002',area:350,production:210},
    {id:'F007',name:'演示农户 007',projectId:'PRJ-002',area:280,production:168},
    {id:'F008',name:'演示农户 008',projectId:'PRJ-003',area:500,production:300},
    {id:'F009',name:'演示农户 009',projectId:'PRJ-003',area:420,production:252},
    {id:'F010',name:'演示农户 010',projectId:'PRJ-003',area:380,production:228},
  ]
  const policies: Policy[] = [
    {id:'POL-001',memberId:'F001',projectId:'PRJ-001',tons:100,area:167,guarantee:2600,deductible:0,cap:20000,start:'2026-07-01',end:'2026-10-10',status:'已结算',settlement:2450,claim:'未申请',payout:15000},
    {id:'POL-002',memberId:'F001',projectId:'PRJ-001',tons:80,area:133,guarantee:2550,deductible:10,cap:16000,start:'2026-09-01',end:'2026-11-30',status:'保障中',settlement:0,claim:'未申请',payout:0},
    {id:'POL-003',memberId:'F002',projectId:'PRJ-001',tons:200,area:333,guarantee:2600,deductible:0,cap:40000,start:'2026-07-01',end:'2026-10-10',status:'已结算',settlement:2450,claim:'待审核',payout:30000},
    {id:'POL-004',memberId:'F003',projectId:'PRJ-001',tons:180,area:300,guarantee:2600,deductible:0,cap:36000,start:'2026-07-01',end:'2026-10-10',status:'已结算',settlement:2450,claim:'已支付',payout:27000},
    {id:'POL-005',memberId:'F005',projectId:'PRJ-002',tons:200,area:333,guarantee:2580,deductible:10,cap:40000,start:'2026-07-01',end:'2026-10-10',status:'已结算',settlement:2460,claim:'待支付',payout:22000},
    {id:'POL-006',memberId:'F006',projectId:'PRJ-002',tons:150,area:250,guarantee:2580,deductible:10,cap:30000,start:'2026-09-01',end:'2026-11-30',status:'保障中',settlement:0,claim:'未申请',payout:0},
    {id:'POL-007',memberId:'F008',projectId:'PRJ-003',tons:250,area:417,guarantee:2600,deductible:0,cap:50000,start:'2026-07-01',end:'2026-10-10',status:'已结算',settlement:2440,claim:'已支付',payout:40000},
    {id:'POL-008',memberId:'F009',projectId:'PRJ-003',tons:200,area:333,guarantee:2600,deductible:0,cap:40000,start:'2026-07-01',end:'2026-10-10',status:'已结算',settlement:2440,claim:'待审核',payout:32000},
  ]
  return {projects,members,policies}
}
function restore(): Store {
  const data = seed()
  try {
    const raw = localStorage.getItem(key)
    if (raw) {
      const stored = JSON.parse(raw)
      // Only restore mutable demo actions; seed records remain the source of truth.
      if (stored && Array.isArray(stored.enrolled)) {
        for (const member of data.members) {
          if (stored.enrolled.includes(member.id) && !data.policies.some(p=>p.memberId===member.id)) data.policies.push(newMemberPolicy(member))
        }
      }
      for (const policy of data.policies) {
        const claim = stored?.claims?.[policy.id]
        if (policy.status==='已结算' && policy.payout>0 && ['未申请','待审核','待支付','已支付'].includes(claim)) policy.claim=claim
      }
      for (const project of data.projects) {
        if (stored?.subsidies?.includes?.(project.id)) project.subsidyPaid=project.subsidyBudget
      }
    }
  } catch { /* Storage may be unavailable; the demo remains usable in memory. */ }
  return data
}
export const business = reactive(restore())
export const storageState = reactive({ warning: '' })
watch(business, () => {
  try {
    localStorage.setItem(key, JSON.stringify({
      claims:Object.fromEntries(business.policies.map(p=>[p.id,p.claim])),
      enrolled:business.policies.filter(p=>p.id.startsWith('POL-M-')).map(p=>p.memberId),
      subsidies:business.projects.filter(p=>p.subsidyPaid===p.subsidyBudget).map(p=>p.id),
    }))
    storageState.warning = ''
  }
  catch { storageState.warning = '浏览器未能保存，本次操作仅在当前页面有效。' }
}, { deep:true })
export function resetDemo() { Object.assign(business, seed()) }
export function advanceClaim(policy: Policy) {
  if (policy.status !== '已结算' || policy.payout <= 0) return
  const next = { '未申请':'待审核', '待审核':'待支付', '待支付':'已支付' } as const
  if (policy.claim !== '已支付') policy.claim = next[policy.claim]
}
export function enrollMember(member: Member) {
  if (business.policies.some(p => p.memberId === member.id)) return
  business.policies.push(newMemberPolicy(member))
}
function newMemberPolicy(member:Member): Policy {
  return {id:`POL-M-${member.id}`,memberId:member.id,projectId:member.projectId,tons:member.production,area:member.area,guarantee:2600,deductible:0,cap:member.production*200,start:demoDate,end:'2026-11-30',status:'保障中',settlement:0,claim:'未申请',payout:0}
}
export function projectSummary(project: Project) {
  const policies = business.policies.filter(p => p.projectId === project.id)
  const members = business.members.filter(m => m.projectId === project.id)
  const insured = members.filter(m => policies.some(p => p.memberId === m.id))
  const eligible = policies.filter(p => p.status === '已结算' && p.payout > 0)
  return {project,policies,members,insured,area:insured.reduce((n,m)=>n+Math.min(m.area,policies.filter(p=>p.memberId===m.id).reduce((total,p)=>total+p.area,0)),0),tons:policies.reduce((n,p)=>n+p.tons,0),
    due:eligible.reduce((n,p)=>n+p.payout,0),paid:eligible.filter(p=>p.claim==='已支付').reduce((n,p)=>n+p.payout,0),
    pending:policies.filter(p=>p.claim==='待审核').length}
}
