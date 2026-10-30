# 玉米数据快照与标准文件

`casde_20261009.json`只转录农业农村部[CASDE-No.124中国玉米供需平衡表](https://scs.moa.gov.cn/jcyj/202610/t20261009_6488446.htm)。随附原始HTML，加载时校验SHA256。发布日期仅精确到日，不虚构发布时分秒。市场年度为10月至次年9月；单位万吨转换为吨。9月预测是10月报告中的比较列，不视作9月在本平台已可得。

玉米表没有期初或期末库存。结余变化保留独立字段，不能用于生成库存水平或库存消费比。用途比例使用同年度、同发布列的C/(C+X)、X/(C+X)。原报告声明为研究预测成果，不作为投资或经营直接依据。

日行情读取项目`var/market`经过校验的离线Parquet，具体合约的closePrice和settlePrice分别提供。快照中的created_at作为该快照在平台可得的依据；历史原始发布时刻未核实。来源回放采用下一自然日可得假设并披露该限制，平台回放不把补录行情伪装为历史时点已在系统可得。

## 人工文件导入

`POST /api/v2/data/imports`只接收文件内容，不下载用户提供的链接。先`mode=preview`，复核通过后提交同内容`mode=confirm`。统一提供source_id、name、source_uri、source_published_at、source_revision、kind、period_type、unit，以及rows数组或csv_content字符串。

贸易文件使用kind=trade，period_type=calendar_month或calendar_year。CSV头为：

```csv
reporter,partner,flow,hs_code,hs_revision,period_start,period_end,value
```

reporter和partner使用明确的国家代码；世界伙伴使用WLD。flow为import/export/reimport/reexport。玉米原粮允许1005、100510和100590。一次聚合不能同时包含HS父项与子项，也不能将世界伙伴与逐国伙伴相加。

供需文件使用kind=supply_demand，period_type=MY或TY。CSV头为：

```csv
entity_code,metric,marketing_year,period_start,period_end,value
```

MY支持production、imports_my、exports_my、domestic_consumption、beginning_stocks、ending_stocks、stock_change、feed_use、food_use、industrial_use。TY仅支持imports_ty、exports_ty。年度标签不能替代实际period_start/period_end。同版本MY的消费和出口齐全时，系统计算用途比例；库存缺失时返回不可计算。

每批单位一致，供需必须为重量单位。任何缺值都不能通过填0代替。不同内容不得使用同一发布版本覆盖；更正须新建source_revision。人工提供的数据均标记manual_unverified，不宣称已由原机构核验。合成演示文件必须传`is_fixture=true`，系统保留fixture质量标识，不与实测记录混淆。当前MySQL初始化DML包含明确标记synthetic的国家供需、贸易等预置记录，与本目录的公开供需原始快照分别管理。

## 研究执行边界

研究统一写入PLATFORM_DATABASE_URL指定的MySQL；未配置时明确报错，不建立本地数据库。数据集、因子、实验、报告均只新增版本，不覆盖历史。研究限制2500条样本、6个因子和注册参数，采用有界同步任务。当前没有后台排队、进程取消或任意脚本训练。

模型包括上一观察值、移动均值、训练期趋势、因子岭回归。岭回归缩放参数只在训练期拟合；验证与测试使用前一观察点因子。测试区间一经返回即视为已查看，后续区间部分重叠也标记重复评估。金额目标是单观察日假设下的保险赔款情景，不替代真实保单采价、核定、期权估值或付款。

`research_seed.json`归档已执行研究的冻结数据、因子、实验、报告及测试区间记录，供离线SQL导出使用；不包含账号、盐、口令哈希或会话。重新导出不再创建临时研究数据库，也不重跑或改写历史研究结果。
