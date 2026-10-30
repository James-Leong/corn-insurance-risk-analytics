# MySQL 数据库设计与初始化

本轮采用MySQL 8.0，业务工作台直接读取数据库中的态势和业务记录。界面以业务字段呈现；样例来源仅在数据字段、导出和本技术文档中保留。当前已由数据库所有者执行DDL，应用账号完成DML导入。

## 交付与执行

- [001_schema_mysql.sql](001_schema_mysql.sql)：39张表及索引、会话外键、结构版本和事务锁。只新增，不执行DROP、TRUNCATE、授权变更或自动升级既有表。
- [002_seed_mysql.sql](002_seed_mysql.sql)：4373条业务和参考数据，不含账号、口令哈希、盐或会话；单事务导入，重复执行保留已存在的记录，尤其不会重置工作区版本、已审批责任或已支付金额。
- [seed-manifest.json](seed-manifest.json)：批次、数据时点、各表行数及DML的SHA256。行数为脚本内初始化记录数，不包括后续会话及日常办理新增。
- [业务接口契约](../../backend/app/platform/CONTRACT.md)：业务对象、操作权限与状态约束。

在客户端选择`grain_guard`库，依次执行DDL、DML。应用账号只有SELECT、INSERT、UPDATE、DELETE权限；运行时不尝试建表或提权。脚本不包含数据库口令。实际连接保存在被Git忽略的本地`.env`中。

本地SSH隧道：

```bash
ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:3313:127.0.0.1:3313 <ssh-host>
```

保持隧道运行。应用使用`PLATFORM_DATABASE_URL=mysql://用户名:URL编码口令@127.0.0.1:3313/grain_guard`；口令中的`@`、`+`等字符需要URL编码。无需将连接串写入SQL、README或前端。

以上环回地址仅适用于本地进程；容器部署应使用容器可达的数据库或同网络命名空间中的隧道地址，不能直接复用宿主机的127.0.0.1。

在已验证的Python 3.12环境，从仓库根目录执行：

```bash
backend/.venv/bin/python --version
backend/.venv/bin/python backend/tools/bootstrap_platform.py --apply
```

`--apply`读取当前DML并通过MySQL客户端执行，不运行DDL。`--export`根据种子定义重新生成SQL及清单，要求本地存在已校验的历史行情快照；它不覆盖数据库中的已有记录。新版本或数据修订须使用新的业务编号和发布版本，不靠重跑种子修改已办业务。

## 表与对象

| 范围 | 表 | 主要字段与用途 |
|---|---|---|
| 结构与事务 | schema_migrations、platform_locks | 安装版本；业务、研究、目录事务协调 |
| 身份 | platform_users、platform_sessions | 账号角色、PBKDF2口令哈希、令牌哈希和有效期；不保存明文密码或令牌 |
| 业务事务 | platform_workspaces、platform_requests | 项目版本聚合及请求指纹、幂等回执 |
| 研究 | research_objects、research_test_exposures | 不可变数据集、因子、实验、报告；测试区间解封记录 |
| 项目与产品 | insurance_projects、insurance_products | 项目地区、产品版本、指定合约、保障价、预算 |
| 申请与保单 | insurance_applications、insurance_policies、application_batches、issuance_requests | 客户、责任数量、保费、申请及出单关联 |
| 再保险 | reinsurance_contracts、reinsurance_allocations | 合同号、相对方、分出比例、限额与责任保单 |
| 对冲 | hedge_plans、trade_orders、hedge_contracts、hedge_allocations | 方案、委托、确认量、预占、合同与责任匹配 |
| 核赔 | price_fixings、insurance_claims | 约定观察、来源版本、规则额、核定额和批准额 |
| 资金 | cash_payables、cash_payments、risk_recoveries、premium_adjustments | 应付用途、批准、实付、预占、回收及批改保费 |
| 管理 | reconciliation_items、business_decisions、business_audit_events | 差异、人工判断、来源上下文和办理历史 |
| 数据目录 | data_sources、data_series、data_observations | 来源、指标、单位、观察日期、可得时点、版本及数值 |
| 期货 | market_contracts、market_daily_bars | 具体合约，分开保存OHLC、结算价、成交量及持仓量 |
| 供需贸易 | supply_balances、trade_monthly | 国家、市场年度、用途、进口出口、伙伴国及HS品种 |
| 农情 | environment_daily、hazard_assessments | 地区、天气、土层、水分、生育阶段、风险概率及评估有效期 |
| 政策 | policy_events | 国家、分类、发布与生效时间、内容摘要和业务关注 |

```mermaid
flowchart LR
  D[行情 / 供需 / 农情 / 政策] --> J[业务判断与研究]
  J --> A[投保申请]
  A --> P[保单责任]
  P --> R[再保 / 对冲安排]
  P --> C[采价与核赔]
  R --> I[再保 / 对冲回收]
  C --> O[客户赔款与付款]
  I --> X[对账]
  O --> X
```

上图是业务关联。身份会话使用数据库外键；跨业务对象的状态、数量与资金引用由同一聚合事务校验，不能把图中每条线理解为已声明数据库外键。

## 存储及写入规则

`platform_workspaces.document`是现有业务状态机的事务权威数据，业务表是同事务更新的结构化查询投影。关键金额与数量使用DECIMAL列，完整条款、历史版本、回执和来源上下文保留在JSON payload。应用命令在MySQL中先锁定业务协调行，再完成状态校验、聚合及投影写入和幂等回执保存；异常一并回滚。应用运行仅使用MySQL，不提供本地数据库回退；测试替身仅位于tests目录。

登录用户由`platform_users`管理，密码保存为带独立盐的PBKDF2哈希，会话保存在`platform_sessions`。MySQL认证仅读取现有账号，不在登录或会话验证时自动补建默认用户；账号删除后也不会自动恢复。尚未提供用户管理页面。登录页不展示凭据，也不预填账号密码；退出登录撤销当前服务端会话。

账号通过私有DML写入数据库，没有固定登录名或默认用户。需要新增实际用户时，在Python3.12环境从仓库根目录运行 `backend/.venv/bin/python backend/tools/generate_user_dml.py --username "<实际登录名>" --name "<姓名>" --role operator --output docs/database/private/003_user.sql`，交互输入至少12字符的密码。角色可选operator、reviewer、customer，只代表权限；工具不按角色名创建账号，不读取密码配置，也不连接或修改数据库。

生成文件权限为0600，包含独立随机盐及PBKDF2密码哈希，不保存明文密码；文件属于被Git忽略的私有部署材料。管理员审核后在目标MySQL库执行INSERT。重复用户名或编号会失败，不自动重置已有账号。关联已有保单等记录时，应以`--user-id`传入业务约定的身份编号，避免破坏责任归属。修改密码须另行审核UPDATE及会话撤销DML，不由环境配置生效。

本轮修改未执行共享库账号DML，现有账号与业务记录保持原样。

不能单独修改`insurance_*`、`cash_*`等投影表来办理业务，否则会与权威聚合不一致。外部业务对接应调用命令接口，或在同一事务中修改聚合并重建投影。本轮没有另写一套承保、对冲、赔款或现金计算引擎。

`data_observations`、`market_daily_bars`等参考数据可由后续生产任务写入，但必须同步数值、来源、发布版本、时点和质量元数据；合同已锁定的采价快照不可随参考数据修订而覆盖。业务资金不能因农情概率或政策事件变化自动扣减或付款。

## 数据口径和来源替换

- `origin_type`：`synthetic`为本轮生成的业务、贸易、国际供需、天气、风险与政策样例；`verified`为已有校验快照，不表示任何未来数据天然可信。`seed_batch`标记初始化批次。业务界面不显示这些技术标识，但API和导出保留，避免后续混入正式来源。
- 政策样例不伪造官方文件编号、发布机关或原文链接；风险概率是已存储的样例评估记录，不代表已训练或验证真实灾害模型。
- 行情沿用已有548条具体合约历史记录，不生成实时交易报价；原始发布时间没有依据时保持为空。数据截至2026年10月23日，农业与政策样例时点为2026年10月29日。
- 国家用途比按同年度`C/(C+X)`与`X/(C+X)`计算，值存0—1，界面显示百分比。CASDE的结余变化不替代期末库存。
- 月度进口按伙伴国分别保存，合计序列由同月伙伴值生成，不重复叠加“世界”合计。MY年度进口和海关月度进口使用独立序列。
- 土壤体积含水量与水分饱和度分别存储，单位为0—1比例，保留0—20厘米土层定义。每个风险评估有地区、灾害类型、as_of、valid_until、horizon_days及模型版本；不返回请求时点之后或已经失效的结果。
- 后续真实采集或生产任务写入新的来源和发布版本，并设置相应来源类别。页面继续使用既有查询接口；需要调整业务规则时另走产品版本与评审流程。

外部出单、交易和支付适配仍保持原有本地状态回执行为，没有因移除界面文案而启用真实资金指令。

## 验证

所有pytest单元测试通过测试目录的SQL替身隔离，防止本地`.env`中的MySQL地址使测试误写共享库；替身不作为应用运行后端。完整浏览器写入测试须使用独立MySQL验收实例。本次账号及MySQL统一改动通过153项单元测试，并经临时隧道完成真实MySQL只读连接及查询校验，没有向共享库新增用户或业务数据。正式事务、外部回执和浏览器写入集成验收应在专用MySQL环境完成。
