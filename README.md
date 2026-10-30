# 玉米保险业务平台

面向既有玉米保险产品的业务团队，采用**玉米态势首页＋四个完整业务模块**：投保与保单、数据与研究、风险转移与组合、结算与赔付。经办与复核共用服务端台账，客户仅访问本人申请、保单及赔付进度。两个下单流程分别是客户投保出单与保险方对冲委托。

开发与部署参见[数据库说明](docs/database/README.md)、[业务接口契约](backend/app/platform/CONTRACT.md)及[决策支持契约](docs/contracts/decision-v1.md)。项目说明、竞标汇报、需求设计和内部评审材料仅在本地维护，不随代码提交。

## 本地运行

后端要求Python **3.12**，前端要求Node.js **22**（`frontend/.nvmrc`）。先验证解释器，再安装依赖及执行命令；不要使用其他系统版本。以下从仓库根目录开始：

```bash
uv python find 3.12
uv sync --directory backend --python 3.12 --locked --extra dev --extra research --extra inference
backend/.venv/bin/python --version
cp .env.example .env
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

首次运行前，按[数据库说明](docs/database/README.md)准备数据与账号。另开终端运行前端：

```bash
source ~/.nvm/nvm.sh
cd frontend
nvm use
node --version
npm ci
npm run dev
```

浏览器访问 `http://127.0.0.1:5173/#decision`；后端接口文档为 `http://127.0.0.1:8000/docs`。VS Code已有本地联合调试配置；其环境文件仍为被Git忽略的根目录`.env`。

## 数据库、账号与数据准备

平台支持MySQL 8.0，提供[39张表DDL](docs/database/001_schema_mysql.sql)、[4373条公共初始化数据](docs/database/002_seed_mysql.sql)及[清单](docs/database/seed-manifest.json)。有权限的数据库所有者执行DDL，应用账号执行DML。幂等种子保留已有记录，不重置工作区或已办业务。公共DML不包含用户、口令哈希、盐、会话或有效凭据。

实际连接仅写入本地`.env`的`PLATFORM_DATABASE_URL`。业务、研究与账号统一使用MySQL，连接配置为必填；未配置时启动报错，不创建任何本地业务数据库。账号由私有DML插入，登录仅读取已有用户，不自动创建或恢复账号。

需要新增实际用户时，在已验证的Python3.12环境生成私有DML：

```bash
backend/.venv/bin/python --version
backend/.venv/bin/python backend/tools/generate_user_dml.py --username "<实际登录名>" --name "<姓名>" --role operator --output docs/database/private/003_user.sql
```

工具交互输入密码，仅生成含随机盐和PBKDF2哈希的INSERT脚本，不连接数据库，不执行账号创建，也不读取密码环境变量。指定实际用户名，角色可选`operator`、`reviewer`、`customer`；角色不等于登录名，不提供内置账号。管理员审核后在目标MySQL库执行私有DML；重复用户名或编号直接失败，不覆盖已有账号。关联既有业务身份时可指定`--user-id`，保持用户ID与业务责任一致。`docs/database/private/`不进入Git；密码不写入明文SQL、命令或文档。

退出登录撤销当前服务端会话。单元测试仅在测试目录注入隔离SQL替身及临时数据，不通过应用配置创建账号，也不连接共享MySQL。

已校验历史行情、公开供需快照与预置业务数据分别保留来源。行情截至2026年10月23日；天气、灾害概率及部分供需贸易、政策为截至10月29日的预置记录，不代表真实灾害模型已生产运行。外部出单、交易和支付目前采用本地回执适配；界面可正常办理，接口与导出保留执行元数据，正式通道需联调。

MySQL可以使用公共DML浏览现有态势与历史案例；运行研究、重新生成行情或采价需要配套的本地Parquet与模型数据。这些大文件不进入Git，部署应另外交付校验过的数据包。离线采集与容器步骤见[离线数据与部署](docs/demo-next/离线数据与部署.md)。

## 四模块业务流程

1. **投保与保单**：逐户申请或批量预览 → 资料 / 条款确认 → 复核核保 → 保费回执 → 出单请求及查单 → 责任版本与批改。核保通过不等于确认出单。
2. **数据与研究**：浏览来源、单位和可得时点 → 冻结数据 → 配置受控因子及时间切分 → 运行注册模型与基线 → 保存版本报告并引用。每次最多2500条观察、6个因子。
3. **风险转移与组合**：核对毛责任、分出和自留 → 关联比例再保 → 场外看跌方案、报价和复核 → 提交委托及分批确认 → 按实际确认合同匹配保单。未知回报保留预占。
4. **结算与赔付**：按约定观察窗口采价并锁定 → 规则额、人工核定、复核批准 → 生成应付 → 付款复核及部分 / 未知回执 → 风险回收与对账。客户赔付不等待再保或对冲回款。

天气和政策支持人工判断，不直接触发价格保险赔付。产品合同规则以业务方确认版本为准；保险资金的股票、基金投资管理不属于本期范围。

## 验证与提交

后端单元测试通过测试目录中的隔离SQL替身验证流程，不连接共享MySQL；MySQL接入需另外执行专用环境集成验收。在backend目录用已验证解释器运行：

```bash
.venv/bin/python --version
.venv/bin/python -m ruff format --check app research tests tools
.venv/bin/python -m ruff check app research tests tools
.venv/bin/python -m pytest -q
```

前端在Node22环境运行`npm run build`。浏览器验收使用已有用户，通过`PLATFORM_TEST_OPERATOR_USERNAME`、`PLATFORM_TEST_REVIEWER_USERNAME`、`PLATFORM_TEST_CUSTOMER_USERNAME`指定各岗位实际登录名，通过`PLATFORM_TEST_PASSWORD`传入验收凭据：`npm run test:decision`为只读页面验收，`npm run test:platform`为业务全链路，`npm run test:review`为本次回归。完整写入测试必须指向独立MySQL验收实例，并显式设置`PLATFORM_TEST_ALLOW_WRITES=isolated`确认环境；禁止对共享业务实例运行。用`APP_URL`、`API_URL`指定验收服务，`BROWSER_EXECUTABLE`可指定Chromium。

提交前从仓库根目录运行 `backend/.venv/bin/python backend/tools/check_submission.py` 扫描暂存内容，`--working-tree`可检查工作区候选；扫描包括Word和PDF。不提交`.env`、私钥、业务数据库、内部调研或账号初始化数据。请在独立开发分支完成检查与代码审查后提交；推送和创建PR按团队安排。

## 部署与架构

前端Vue3＋TypeScript，后端FastAPI；`backend/app/platform`集中处理身份、业务状态、事务持久化和保险业务研究。业务聚合、查询投影和幂等回执同MySQL事务写入，不能通过单独修改投影表办理业务。[业务接口契约](backend/app/platform/CONTRACT.md)和[决策支持契约](docs/contracts/decision-v1.md)说明字段和状态。

`docker compose up --build`可构建并启动，前端5173、后端8000。Compose将本地`var`只读挂载为行情和模型目录，业务与研究状态存入MySQL；MySQL连接地址必须从容器可达，不能复用宿主机环回隧道。生产环境应配置数据授权、身份、真实外部适配、备份恢复、监控及容量验收。
