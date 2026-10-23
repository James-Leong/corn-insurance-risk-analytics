# Comparison v1：只读研究结果契约

数据范围固定为 2025-12-31 至 2026-10-23，日期含端点。结果限研究用途，短历史不能证明业务可用。Web 请求不访问行情 SDK、不训练模型。

存储根目录 `COMPARISON_STORE_DIR`，默认 `var/comparison`。模式 `COMPARISON_DATA_MODE=measured`（默认）或 `schema_fixture`，两种来源不能混读。

`catalog.json`：
```json
{"schema_version":"comparison-v1","runs":[{"run_id":"corn-2026-v1","comparison_group_id":"corn-price20","sha256":"bundle文件的SHA256"}]}
```
`runs/<run_id>/bundle.json`：
```json
{
  "schema_version":"comparison-v1",
  "run_id":"corn-2026-v1", "comparison_group_id":"corn-price20",
  "title":"玉米价格险研究", "created_at":"2026-10-24",
  "source_kind":"measured", "label_kind":"rule_generated", "run_status":"completed",
  "data_start":"2025-12-31", "data_end":"2026-10-23",
  "warnings":["仅供研究，非当前保单预测"],
  "protocol":{"task":"payout_risk","window_trading_days":20,"data_version":"snapshot-id","rule_version":"rule-v1","split_version":"split-v1","sample_hash":"sha256"},
  "selection":{"frozen":false,"selected_method_id":null,"reason_code":"not_evaluated"},
  "test_review":{"approved":false}, "released_partitions":["validation"],
  "partitions":{"validation":{
    "sample_count":0,"date_count":0,
    "models":[{"method_id":"historical_blocks","model_version":null,"release_state":"research_only","coverage":0,"failure_count":0,"reason_code":"insufficient_data","metrics":[{"metric_id":"expected_payout_rmse","value":null,"unit":"CNY","direction":"lower_is_better","missing_reason":"insufficient_data"}]}],
    "evidence":{"calibration":[],"error_slices":[],"data_quality":[]},
    "cases":[]
  }}
}
```

模型字段：`method_id` 为 historical_blocks/glm_hurdle/xgboost_hurdle/price_last/price_ma20；风险与价格任务由 model.task（默认 payout_risk）区分。`release_state` 为 research_only/eligible_for_pilot/rejected/not_evaluated。coverage 为 0—1。方法失败保留行，null 不得显示成 0；schema_fixture 不允许数值成绩或选择冠军。指标每项必须提供 unit、direction，缺失必须提供 missing_reason。

历史个案：`{case_id,valuation_date,contract_id,guarantee_price,quantity_tons,observed_payout,outputs:[{method_id,claim_probability,expected_payout,p90_payout,p90_status,reason_code,scenario_payout}]}`。金额 CNY、价格 CNY/吨、概率 0—1；P90 为 null 时显示 p90_status（unsupported/not_validated/insufficient_data），不得补零。价格参考仅提供 scenario_payout。个案字段之外可补充观察窗口等公开说明，不包含私密保单信息。

API 前缀 `/api/v1/comparisons`：

| GET | 返回 |
|---|---|
| `/groups` | `{schema_version,data_mode,default_group_id,empty_reason,items:[{comparison_group_id,title,run_count}]}` |
| `/groups/{group_id}/runs` | `{items:[元信息]}` |
| `/runs/{run_id}?partition=validation` | 元信息；不包含 partitions，仅含可公开 released_partitions；分区未发布拒绝 |
| `/runs/{run_id}/metrics?partition=validation` | `{schema_version,run_id,comparison_group_id,source_kind,label_kind,partition,selection,sample_count,date_count,models}` |
| `/runs/{run_id}/evidence?partition=validation&view=calibration` | `{run_id,partition,view,items:[...]}`；view 为 calibration/error_slices/data_quality |
| `/runs/{run_id}/cases?partition=validation&case_id=...` | `{run_id,partition,items:[个案]}`；无 case_id 返回全部 |
| `/runs/{run_id}/export?partition=validation&format=json` | JSON 含 metadata、metrics、evidence、cases，仅当前分区；CSV 为指标长表并携带身份、数据范围、单位、限制 |

详情、列表、图表、个案与导出均不能泄漏未发布测试分区。test 仅在 selection.frozen、test_review.approved 且 released_partitions 包含 test 时可读。错误体 `{detail:{code,message}}`：未发布分区409 partition_not_released；未知ID404 comparison_not_found；坏包503 comparison_bundle_invalid；未知筛选422；目录不存在或尚无 catalog 为正常200空列表（no_published_results）。ID只允许字母数字下划线短横线，最长80字符。

catalog中的SHA256必须匹配整个bundle文件字节；API仅读取登记目录，拒绝软链接、越界路径、非法数值及未知schema。报告最多10MB，个案与证据视图最多2000条。发布端先完成校验并写入新run目录，再原子替换catalog；禁止覆盖既有批次。
