export type Role = 'farmer' | 'cooperative' | 'insurer' | 'authority'
export type Page = 'overview' | 'records' | 'market' | 'scenario' | 'comparison' | 'analysis'

export const workspaces = {
  farmer: {
    label: '农户', title: '我的收益保障', description: '查看本季保单、保障期限和理赔进度，办理赔付申请。',
    overview: '我的保障', scenario: '保障试算', action: '调整我的保障', quantity: '计划保障数量',
    initial: { insured_tons: 100, guarantee_price: 2600, settlement_price: 2450, deductible_per_ton: 0, payout_cap: 20000 },
  },
  cooperative: {
    label: '合作社', title: '合作社保障统筹', description: '跟进成员参保、保障规模与赔付到账，查看逐户保障明细。',
    overview: '保障统筹', scenario: '集体保障试算', action: '调整集体保障', quantity: '成员合计保障数量',
    initial: { insured_tons: 1000, guarantee_price: 2600, settlement_price: 2450, deductible_per_ton: 0, payout_cap: 200000 },
  },
  insurer: {
    label: '保险机构', title: '承保与理赔管理', description: '管理项目保单、审核理赔与赔款支付，跟踪保费及对冲资金。',
    overview: '承保分析', scenario: '合同赔付试算', action: '调整赔付试算', quantity: '情景承保数量',
    initial: { insured_tons: 1000, guarantee_price: 2600, settlement_price: 2450, deductible_per_ton: 0, payout_cap: 200000 },
  },
  authority: {
    label: '农业管理部门', title: '农业项目监管与政策落实', description: '跟进保障覆盖、补贴拨付与赔付兑现，查看各地区项目执行情况。',
    overview: '政策落实总览', scenario: '区域情景分析', action: '设置区域情景', quantity: '假设区域保障数量',
    initial: { insured_tons: 10000, guarantee_price: 2600, settlement_price: 2450, deductible_per_ton: 0, payout_cap: 2000000 },
  },
} as const
