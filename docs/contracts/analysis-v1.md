# 历史研究合同分析接口 v1

GET `/api/v1/analysis/options` 返回固定模型 `corn-2026-v1` 的已发布 validation 合约及估值日，支持比例0.95/1/1.05。默认c2701、2026-09-17、100吨、资金预算5000元。

POST `/api/v1/analysis/estimate` 输入：

```json
{"ticker":"c2701","valuation_date":"2026-09-17","strike_ratio":1,"quantity":100,"budget":5000,"deductible":0,"payout_cap":null,"shocks":[-10,-5,0,5]}
```

- quantity为吨，范围(0,100000]；budget、payout_cap为元；deductible为元/吨。
- payout_cap=null代表无封顶，0代表最多赔0元；不能互换。
- shocks为相对估值日结算价的百分比冲击，范围[-50,50]，最多9项，不得重复。
- 未支持比例、训练期估值日、未知输入字段返回422；模型/缓存缺失或校验失败返回503及中文说明。
- 请求不会训练、写文件或调用数据平台。模型目录由服务端配置，前端不能提供路径。

输出 `analysis-v1` 包含 request 快照、contract（保障价、数量、估值日、观察起止）、三方法 methods、price_references、事后 observed、确定性 stress、版本 versions、warnings 和稳定 report_id。相同输入、相同数据模型得到相同报告编号。模型输出为无免赔、无封顶研究条款；免赔和封顶只影响压力情景，不改变模型概率和预期赔款。

输出金额以元计，价格以元/吨计，概率为0—1。前端展示时舍入，不改变报告原值。事后均价、赔款不得混入估值特征或称为预测。`p90_payout`均为null。没有生产默认获胜模型。

模型反序列化前校验固定清单及SHA256，报告与模型绑定，Parquet快照与训练数据版本绑定。目录须由部署人员从可信来源只读挂载；哈希用于检测损坏，不代替来源信任或数字签名。
