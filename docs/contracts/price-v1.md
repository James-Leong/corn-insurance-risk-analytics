# 价格参考接口 v1

`GET /api/v1/prices/overview?ticker=c2701`，不传 ticker 默认 c2701。离线结果读取，无训练、SDK或联网。

- schema_version: price-v1; model_version: price-2026-v1
- data_start / data_end: 2025-12-31 / 2026-10-23
- tickers: [{ticker, last_trade_date}]
- ticker, as_of, latest_settlement, last_trade_date
- series: [{date, settlement}]，所选具体合约完整有效历史
- forecast: {status: available|unavailable, reason: string|null, horizon_trading_days:20, target: future_mean_settlement, target_dates:null, methods:[{method_id,value}]}
- methods 三项：price_last、price_ma20、price_ridge；均为未来20交易日均价的点参照，非逐日预测，非区间；value单位元/吨。到期合约不提供未来参照。未缓存未来交易日历，因此 target_dates 始终为 null，不虚构日期。
- validation: {partition:validation, sample_count, date_count, methods:[{method_id,mae,rmse,bias}], backtest:[{as_of,label_available_at,actual,price_last,price_ma20,price_ridge}]}。为所选合约，同一队列比较；无验证样本时 methods/backtest为空。
- warnings: string[]

未知合约404，非法参数422，离线产物缺失/校验失败503。报告按同一价格险分割边界做purge；Ridge固定alpha=1，训练集拟合标准化与模型，验证集不参与调参，最终测试未打开。参数JSON单独保存。历史验证与2026-10-23起点的未来参照分别展示。
