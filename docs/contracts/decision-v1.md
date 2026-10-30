# Decision v1 接口契约

本文为内部开发契约，不替代产品条款或正式功能需求。统一前缀为`/api/v2/decision`，认证复用Bearer会话。仅operator、reviewer可访问，服务端同时检查project_id范围；customer返回403，无会话返回401。

## V3.0数据库数据分支

本轮增加数据库来源，保留decision-v1的鉴权和决策参考语义。数据库初始化方式和样例标识见[数据设计](../database/README.md)。以下原有缺口回执仅适用于数据库中没有对应记录的情况，不再代表已初始化项目的默认结果。

- dashboard.agri_risk在存在资料时返回`status:available`、`latest_observation`、`history`、`regional_observations`、当前地区`assessments`及跨地区`all_assessments`。记录保留origin_type、seed_batch、模型版本和有效期。
- dashboard.policy和policy-events在存在资料时返回`status:available`及实际存储的items。每项有id、国家、分类、标题、摘要、发布时间、生效时间、来源名称及business_impact；样例不伪造官方文号或原文链接。
- source_context增加environment_version、risk_model_version、risk_as_of、policy_version；sources返回实际登记来源，不能把样例数值归因于未采集的官方入口。
- futures优先读取market_contracts和market_daily_bars；data/query读取data_observations。行情仍按具体合约和交易日处理，来源版本随记录保留。
- capabilities在本项目资料齐备时返回`status:available`与目录项；旧的partial缺口结果保留供无资料项目使用。
- risk-assessments查询已保存评估，不运行现场训练或推理。只有请求地区、灾害类型、评估时点、有效期及期限均匹配时返回available、items及概率；不会返回未来记录、过期记录或用不覆盖期限的结果替代。无覆盖时保留not_ready和null概率，前端正常空结果不显示开发进度文案。
- 数据库样例概率不等于已验证真实灾害模型。context_only和not_claim_trigger继续为true，查询不会自动承保、交易或核赔。

## 基础及无资料分支

所有成功回执携带：

```json
{
  "schema_version": "decision-v1",
  "context_only": true,
  "not_claim_trigger": true,
  "notice": "本页用于承保与客户服务决策参考；当前产品为价格保险，天气、土壤及灾害提示不直接触发合同赔付。"
}
```

页面可记录来源快照与人工业务判断；这些接口不创建申请、保单、交易、赔案或支付。POST风险评估只检查字段与返回能力缺口，没有运行灾害预测。正常项目首次访问沿用既有工作台初始化机制，已有业务对象及revision不因聚合查询改变。

## GET /dashboard?project_id=PRJ-001

| 字段 | 类型／说明 |
|---|---|
| project_id | 当前授权项目 |
| project | 当前项目摘要，含id/name/region/status等既有字段 |
| product | 当前产品快照；当前为模拟价格保险，含contract/price_field/official_ready/execution_mode |
| market | `{status,default_ticker,cards,unit,source_id,warnings}` |
| market.cards[] | `{ticker,name,date,as_of,open_price,high_price,low_price,close_price,settle_price,settle_change,settle_change_ratio,volume,open_interest,quality_flag,source_published_at,observation_count,first_date,last_date,is_product_contract,source_version,not_live}` |
| supply_demand | 当前CASDE列及指标，见下文 |
| agri_risk | `{status:'not_ready',risk_level:null,probability:null,model_id:null,missing_requirements,sources,notice,soil_definition_notice}` |
| policy | `{status:'not_connected',items:[],sources,notice}` |
| coverage[] | `{id,name,status,source_uri,note}`，展示已接入和未接入范围 |
| sources[] | 农情及政策官方原文入口，`{id,name,source_uri,status:'reference_only',note}` |
| source_context | 供人工决策记录冻结的来源上下文，见下文 |

market.cards优先排列产品指定合约，其余按合约名排序。三个合约具有各自日期和行情，不拼接、不取平均。行情缺失或校验失败时market.status=unavailable，cards为空，warnings说明原因；产品合约缺失而其他历史合约存在时为partial，不用其他合约替代产品合约。

supply_demand包含`status,source_id,source_name,source_uri,release_id,source_revision,published_at,publication_time_precision,first_seen_at,marketing_year,statistic_status,is_forecast,period_type,period_start,period_end,unit,original_unit,metrics,notes,not_live`。

当前使用CASDE-No.124最后一列，即2026/27“10月预测”，source_revision=202610-forecast。不是9月对照列，也不是最终实际值。吨数由原文万吨×10000；用途比例保持小数。

metrics每项为`{id,name,value,unit,raw_value,original_unit,formula,unavailable_reason,components,components_unit}`。指标包括production/imports_my/domestic_consumption/food_use/feed_use/industrial_use/seed_use/loss_other/exports_my/stock_change/ending_stocks/domestic_share/export_share/stocks_to_use。不存在的期末库存与库存比例为null，不能以结余变化替代。

source_context字段：

```json
{
  "market_version": "market.parquet的SHA256完整值或null",
  "casde_version": "CASDE-No.124-20261009或null",
  "data_as_of": "2026-10-23",
  "market_as_of": "2026-10-23",
  "casde_published_at": "2026-10-09",
  "market_first_seen_at": "快照created_at或null",
  "source_status": {"market": "available", "casde": "available"},
  "built_at": "聚合回执构建时刻ISO8601",
  "not_live": true
}
```

上述日期为当前文件元数据，未来更新按实际快照返回。data_as_of表示市场观察最新日期，不能作为所有数据的统一发布日期；CASDE发布日期另列。任一来源缺失，对应version和日期返回null，source_status为unavailable。缺失不生成假版本。

## GET /futures?project_id=PRJ-001&ticker=c2701

ticker可省略，默认读取产品contract。仅接受形如c2701的具体合约代码。指定或默认合约不在校验快照中返回404；行情损坏返回503，不回退模拟数据或过期合约。

返回：

```text
{
  ticker, default_ticker,
  contract_choices:[{ticker,name,is_product_contract,first_date,last_date}],
  history:[{
    date,open_price,high_price,low_price,close_price,settle_price,
    settle_change,settle_change_ratio,volume,open_interest,
    quality_flag,source_published_at
  }],
  latest:<history末项>,
  unit:'元/吨',volume_unit:'手',open_interest_unit:'手',
  source_id:'uqer',source_uri,source_version,as_of,not_live:true,
  source_context,warnings,
  ...共同回执
}
```

- OHLC分别来自openPrice/highestPrice/lowestPrice/closePrice；settle_price来自settlePrice，互不替代。
- settle_change为本观察日结算价减本合约上一观察交易日结算价；不按自然日前推，不拿其他合约或preSettlePrice字段冒充相邻观察点。
- settle_change_ratio为差额／上一观察交易日结算价，小数比例，展示百分数须×100。
- 首个观察点没有前值时日变化为null；成交量、持仓或OHLC缺字段、缺值或非有限值均为null，不填0。
- as_of为所选合约最后观察日；不同合约可能不同。source_version使用market.parquet SHA256。
- 原始发布时间未核实，source_published_at=null；来源可得时点假设不能变成“已验证16:00发布”。

## GET /capabilities?project_id=PRJ-001

返回`status:'partial'`、`items`、`sources`、`soil_definition_notice`、`risk_request_fields`及共同回执。items覆盖行情供需、环境数值、灾害预测、政策事件。行情供需状态根据实际文件校验结果生成，不能因目录存在就宣称接入成功。

农情及政策sources是官方入口，不是当前地区数据、当前预警或新闻摘要。页面不得将未接入状态显示为“正常”“低风险”。

## GET /policy-events?project_id=PRJ-001

返回`{status:'not_connected',items:[],sources,notice,...共同回执}`。当前没有政策事件，只有农业农村部、财政部和USDA官方原文入口。禁止生成日期、新闻或影响分数补齐页面。

## POST /risk-assessments

请求契约：

```json
{
  "project_id": "PRJ-001",
  "region_code": "230000",
  "region_name": "黑龙江省",
  "crop": "maize",
  "growth_stage": "unknown",
  "as_of": "2026-10-25T08:00:00+08:00",
  "hazard_types": ["lodging", "waterlogging"],
  "horizon_days": 7
}
```

该示例只有查询参数，不含预测数值。region_code必须六位字符串；只校验格式，不宣称行政区映射或覆盖已经核实。crop仅支持maize。as_of必须带时区。growth_stage支持unknown/seedling/jointing/tasseling/grain_filling/maturity；不填默认为unknown。hazard_types支持lodging/waterlogging/drought/frost，1至4项，不得重复。horizon_days严格整数，1至30，默认7。额外字段返回422，不能由调用方提交risk_level或probability伪装模型结果。

成功回执固定为：

```text
{
  status:'not_ready',request:<规范化输入>,risk_level:null,probability:null,
  model_id:null,model_version:null,
  missing_requirements:[
    {id:'environment_observations',name,status:'not_connected'},
    {id:'spatial_mapping',name,status:'not_connected'},
    {id:'crop_context',name,status:'not_verified'},
    {id:'validated_hazard_model',name,status:'not_available'}
  ],
  sources,soil_definition_notice,message,
  ...共同回执
}
```

HTTP200只表示输入契约受理，status=not_ready明确表示没有执行预测。当前不返回评估概率、风险等级、模型版本或保单赔款。土壤含水量、相对湿度、水分饱和度保留各自测量方法、深度、单位和参照基准，不能直接互换。

## 二期字段预留

环境源接入需提供region/plot、station/grid、CRS、空间分辨率、metric、unit、soil_depth、measurement_method、reference_basis、observed/forecast/reanalysis、observation_time、published_at、valid_start/end、lead_hours、first_seen_at、source_revision、quality与授权范围。灾害模型还需作物阶段、地区匹配、目标定义、验证范围、误报漏报或校准指标、模型批准版本及缺输入策略。

政策事件需提供原机构、国家／适用地区、文件号、公布／生效／失效日期、商品范围、原文版本、人工影响说明和复核状态。风险提示、验证模型输出与正式赔款依据分别保存；当前接口不承诺二期数据与模型已交付。
