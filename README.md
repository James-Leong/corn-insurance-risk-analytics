# 玉米价格预测与农业保险风险分析 Demo

面向课程投标汇报的单仓库原型：支持四类业务视角、价格险规则试算和保险机构的多方法评估。真实行情从本地Parquet快照读取，模型比较从离线生成的结果包读取；网页请求不调用UQER或训练模型。当前数据范围固定为2025-12-31至2026-10-23。无快照时auto模式明确展示模拟行情；已配置但损坏的快照报错，不自动降级。

## 本地开发

```bash
cd backend
uv sync --extra dev --extra inference
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Python 使用 3.12（与后端镜像一致），先验证解释器版本，再创建虚拟环境。前端使用 Node.js 22：另开终端执行 `source ~/.nvm/nvm.sh && cd frontend && nvm use && npm ci && npm run dev`。浏览器访问 `http://localhost:5173`，API 文档位于 `http://localhost:8000/docs`。

后端代码提交前，在 `backend` 目录运行 `uv run --extra dev ruff format app tests` 格式化代码，并运行 `uv run --extra dev ruff check app tests` 检查 lint 规则。

提交代码时，请从最新的 `main` 创建自己的开发分支。修改后，在 `backend` 目录运行 Ruff 格式化和 lint 检查，通过后提交并推送分支，再创建目标为 `main` 的 Pull Request。GitHub Actions 会自动运行 Ruff 检查；若检查失败，请修复问题并再次推送。检查通过且完成 review 后再合入。

## 容器：独立构建和启动

```bash
docker compose build backend && docker compose up backend
# 另一个终端
docker compose build frontend && docker compose up frontend
```

也可 `docker compose up --build` 同时启动。backend 与 frontend 使用各自 Dockerfile，可独立构建/部署。

## 预构建镜像部署

可在构建环境预先生成镜像并导出，在部署环境导入后启动。Compose 使用固定镜像名：

```bash
docker compose build
docker save -o corn-insurance-images.tar corn-insurance-backend:latest corn-insurance-frontend:latest
```

将镜像包和 `docker-compose.yml` 放到部署环境，在项目目录导入并启动：

```bash
docker load -i corn-insurance-images.tar
docker compose up -d --no-build
```

部署环境需要Docker Compose和数据目录：将`var/market`、`var/comparison`、`var/models`及`var/price`一起复制到服务器，或解压最新演示数据包。Compose默认以只读方式挂载`./var:/data`，无需UQER token。也可用`DEMO_DATA_DIR`指定目录。`pull_policy: never`使用本地已导入镜像；构建与部署的CPU架构需兼容。完整步骤见[离线数据与部署](docs/demo-next/离线数据与部署.md)。

## VS Code 一键本地启动

1. 在项目根目录准备`.env`（首次可复制`.env.example`），已有数据使用`DATA_PROVIDER=parquet`，无数据可用`auto`。网页运行不需要令牌；`.env`已被Git忽略。
2. 按上面的本地开发步骤使用 `uv sync --extra dev --extra inference` 创建 `backend/.venv` 并安装依赖；在 `frontend` 的Node22环境执行 `npm ci`。
3. 用 VS Code 打开项目根目录，安装 Python/Python Debugger 扩展；在“运行和调试”选择 **Corn Risk Demo: Local Development**，按 F5 同时启动前后端。

前端：`http://127.0.0.1:5173`；后端：`http://127.0.0.1:8000/docs`。调试配置从根目录 `.env` 注入后端环境变量；不要把 `.env` 提交到 Git。

## 离线 UQER 与 Parquet

UQER仅用于显式离线取数命令`python -m research.ingest`，按请求身份缓存Parquet与SHA256校验信息；已缓存请求不再调用SDK，`--offline`模式可在无token环境重新整理快照。行情使用具体合约的`settlePrice`，不拼接连续合约或以收盘价替代。研究命令`python -m research.run`仅消费快照。以上命令均在已验证的Python3.12虚拟环境运行，安装及完整路径见[离线数据与部署](docs/demo-next/离线数据与部署.md)。旧`DATA_PROVIDER=uqer`仅兼容映射到缓存读取，不再在线取数。

## Demo 路径与业务边界

1. 切换四类角色，查看个人保单、合作社成员、保险机构承保与理赔、农业管理部门区域项目。业务台账使用关联的 Mock 数据，首页指标由台账汇总。
2. 农户提交模拟理赔申请，保险机构审核并模拟支付；各角色赔付统计同步更新。合作社可为未参保成员建立模拟保单，管理部门可查看覆盖情况、模拟拨付补贴。
3. 台账支持搜索、状态/地区筛选、详情和 CSV 导出。模拟操作保存在本机浏览器，刷新保留，可确认重置。
4. 从保单详情带入试算，或在独立试算页调整保障价、情景价、免赔额、数量与上限；各角色分别保留会话输入，试算不修改台账。
5. 行情和参考估计位于辅助页面。农业管理部门首页以覆盖率、补贴执行、赔付兑现及项目跟进为核心。
6. 保险机构“模型评估”提供固定历史合同、三方法对照、验证报告及JSON/CSV导出。研究标签来自历史结算价与规则，不是真实赔案；当前不足一年数据，仅作研究，不宣布生产模型或已验证P90。
7. 保险机构“玉米行情”支持合约切换及20日平均结算价预测；点击“带入客户风险分析”进入研究合同、风险与压力、业务判断、承保方案、赔付试算、分析报告六步向导。业务人员记录参考方法、风险限额和判断依据，接受后确认方案并按同一组条款试算；调整或拒绝承保分别进入对应分支。保存的模型在可信只读挂载目录中校验后加载，网页不训练、不取外部数据。未来价格参照与历史合同回放的日期明确分开。

角色切换仅为演示，不构成身份认证或数据权限隔离。

示例公式：`赔付 = min(max(保障价 - 结算价 - 每吨免赔额, 0) × 承保吨数, 赔付上限)`。这只是演示规则；实际实现必须遵循合同规定的价格来源、基差、触发、费率、赔付上限和结算日。期货价不等于保单结算价，预测不等于实际赔付，演示模型不用于投保决策。

## 架构

- `backend/app/api`: HTTP 路由与请求 schema
- `backend/app/domain`: 不依赖框架的保险领域计算
- `backend/app/services`: 用例编排
- `backend/app/adapters`: Parquet快照和显式模拟行情适配层
- `backend/app/repositories`: 校验后读取行情快照和不可变比较报告
- `backend/research`: 离线取数、标签、时间切分、训练、评价与发布
- `frontend`: Vue 3 + TypeScript + Vite 单页应用
- `docs`: 系统架构和后续迭代路线
