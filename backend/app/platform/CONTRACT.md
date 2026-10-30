# 四模块工作台 API 契约

业务存储支持MySQL 8.0；运行账号只执行DML。项目聚合、结构化查询表和请求回执同事务写入，外部执行适配仍保留 `execution_mode: simulation` 元数据，不发送真实资金指令。界面按正常业务字段展示，初始化来源由origin_type和seed_batch追踪。

`POST /api/v2/session {username,password}` 返回 `{token,user,expires_at}`。
账号由MySQL管理；通过 `tools/generate_user_dml.py --username --name --role --output` 交互生成私有INSERT脚本，由管理员审核执行。工具不连接数据库，不读取密码环境变量；公共种子与代码没有固定账号或内置口令，认证不自动创建用户。
`DELETE /api/v2/session` 撤销当前Bearer会话，返回204；旧令牌随后返回401，其他会话不受影响。
`user={id,username,name,role,project_ids}`。客户ID为 `USR-CUSTOMER`。

所有后续请求携带 `Authorization: Bearer <token>`。
`GET /api/v2/workspace?project_id=PRJ-001` 返回快照，storage_backend固定为mysql。写入式浏览器验收须指定独立MySQL实例并确认隔离；共享工作区只执行只读验收。
`POST /api/v2/workspace/commands` 请求：
`{request_id,project_id:"PRJ-001",command,target_id?,expected_version?,payload:{}}`。
目标对象操作须传其 `version`；创建/批量预览无目标无需版本。
成功 `{snapshot,result,message}`；错误 `detail:{code,message}`。

| 命令 | target | payload / 行为 | 角色 |
|---|---|---|---|
| decision.record | 无 | region,disposition:proceed/hold/review,reason,source_context?；人工判断只读保存，不替代核保或交易审批 | 经办/复核 |
| application.create | 无 | applicant_name,insured_name,tons,area_mu,region,phone,period_start,period_end,terms_confirmed,materials:[名称],decision_id?。创建草稿，customer_id默认USR-CUSTOMER；内部判断须为本项目记录，冻结decision_snapshot；客户不可引用内部判断 | 经办/客户 |
| application.update | 申请 | 同上，变更后重新核保 | 经办/本人 |
| application.submit | 申请 | terms_confirmed:true，必填材料 | 经办/本人 |
| application.withdraw | 申请 | reason；尚未出单且未收保费时撤回 | 经办/本人 |
| application.import_preview | 无 | rows:[上述逐户字段] | 经办/客户 |
| application.import_confirm | 批次 | 无，通过行全部创建草稿；错误行阻断确认 | 经办/客户 |
| application.review | 申请 | decision:approved/needs_materials/rejected,reason | 复核 |
| application.premium | 申请 | amount,reference。模拟保费回执，允许部分缴费 | 经办 |
| policy.issue | 申请 | 无。发送模拟出单请求，进入issuing | 经办 |
| policy.query | 申请 | outcome:confirmed/unknown/failed（默认confirmed）。查回同一模拟保单 | 经办 |
| policy.change | 保单 | 经办tons或terminate:true,reason；复核action:approve/reject | 经办发起/复核确认 |
| premium.adjustment_confirm | 批改保费记录 | amount,reference；确认新增保费，可部分确认 | 经办 |
| reinsurance.allocate | 再保安排 | policy_id,ratio（0到1）,reference。仅已接受的演示比例安排 | 复核 |
| hedge.plan | 无 | name,policy_ids:[id],tons,tool:otc_put,strike_price,premium_per_ton,report_id?,reason | 经办 |
| hedge.update | 计划 | tons,strike_price,premium_per_ton等；原批准失效 | 经办 |
| hedge.quote | 计划 | premium_per_ton,quote_expires_at:ISO8601,reference；默认有效30分钟的模拟报价 | 经办 |
| hedge.review | 计划 | decision:approved/rejected,reason | 复核 |
| hedge.submit | 计划 | 无。预占责任和预算，生成执行请求，不视为成交 | 经办 |
| hedge.confirm | 执行请求 | cumulative_tons（累计实际确认量）,event_id,final:false/true。最终余量释放 | 复核 |
| hedge.query | 执行请求 | outcome:unknown/rejected/confirmed,cumulative_tons?,event_id?；unknown保留预占 | 经办 |
| hedge.allocate | 对冲合同 | policy_id,tons。仅分配已确认量，保单和交易双侧限制；复核可用allocation_id,action:reconfirm/release,tons?,reason处理批改后分配 | 经办/复核 |
| fixing.prepare | 无 | policy_id；默认校验读取真实本地行情快照；缺失不填零。测试可prices:[{date,value}],reason，标明人工模拟 | 经办 |
| fixing.confirm | 采价 | reason；价格完整后锁定 | 复核 |
| claim.calculate | 无 | policy_id,fixing_id,assessed_amount?,reason?；仅锁定采价，未批准不生成应付 | 经办 |
| claim.review | 赔案 | decision:approved/rejected,approved_amount?,reason | 复核 |
| claim.correct | 赔案 | assessed_amount,reason。更正保留历史、再批准只生成差额 | 经办 |
| payment.create | 应付 | amount,reference。预占余额待审 | 经办 |
| payment.review | 付款 | decision:approved/rejected,reason。批准后模拟发送 | 复核 |
| payment.receipt | 付款 | outcome:unknown/partial/success/failed,cumulative_amount?,event_id,reference。累计值去重 | 经办 |
| recovery.confirm | 回收 | amount,reference。确认应收不等于到账 | 复核 |
| recovery.receipt | 回收 | amount（本次金额）,event_id,reference。分用途到账 | 经办 |
| reconciliation.run | 无 | 无。生成具体未结差异 | 经办 |
| reconciliation.resolve | 差异 | reason,reference。复核处理，不抹去原始差异 | 复核 |
| project.close | 项目PRJ-001 | reason。未结事项阻断结案 | 复核 |

集合：projects,applications,policies,batches,issuance_requests,reinsurance,reinsurance_allocations,
plans,executions,hedges,allocations,fixings,claims,payables,payments,recoveries,reconciliations,
tasks,audit_events；另有 product,summary,portfolio,revision,as_of,execution_mode。
实体均含id,version,status,created_at；所有金额/吨数为JSON number，服务端Decimal计算。

新增 `decision_records` 集合。人工判断固定当前product_id/product_version/contract，source_context保存market_version、casde_version、data_as_of及可选source_status；缺失来源允许null并保留缺口。市场版本使用market.parquet校验哈希，CASDE版本使用release_id。额外verified_source_versions记录服务器核验的本地版本，人工提交的上下文不会被当作已核验来源。记录不可原地更新，新增判断需新建记录。

客户快照的claims仅保留本人保单赔案，新增paid_amount、unpaid_amount、in_transit_amount、payment_status及payment_progress（approved_amount/paid_amount/unpaid_amount/in_transit_amount/status）。金额仅从该赔案的claim用途应付派生，不含权利金、分保保费、退款或其他客户。payables/payments等内部集合仍为空，申请的decision_id/decision_snapshot及全部decision_records均不向客户返回，命令结果也执行相同脱除。

采价审计中，source_version使用已校验market.parquet的sha256；source_snapshot独立保存文件名、哈希、created_at及请求范围。原始行情发布时间未核实时，逐日published_at/source_published_at为null，publication_time_precision为unavailable。snapshot_created_at只表示离线快照创建时间，不能代替原始发布时间。人工模拟值另存recorded_at，不伪造行情发布时间。

`payables.kind`：claim（赔款）、hedge_premium（期权权利金）、reinsurance_premium（分保保费）、premium_refund（批改退款）。
上述应付均复用payment.create/review/receipt；claim_id可空，不能假定全部应付都是赔款。
实际成交累计确认量产生唯一权利金应付并随确认增量调整；再保分配产生分保保费；批准保单减量产生退款。
批准增量的待收保费在premium_adjustments集合，可用premium.adjustment_confirm登记模拟回执。
保单期间必须覆盖演示产品的固定2026年10月19日至23日采价窗。

主要状态：申请draft/needs_materials/submitted/approved/rejected/issuing/issued；
保单active/terminated；计划draft/quoted/approved/rejected/executing/executed/invalidated；
执行processing/unknown/partially_confirmed/confirmed/rejected；
采价missing/pending_review/locked；赔案pending_review/rejected/zero_closed/payable/partially_paid/paid；
付款pending_review/processing/unknown/partially_paid/paid/failed；
回收expected/confirmed/partially_received/received。

`GET /api/v2/workspace/report?project_id=PRJ-001` 导出服务器生成的JSON业务报告（客户不可访问）。
