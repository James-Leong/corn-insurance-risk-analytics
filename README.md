# 玉米价格预测与农业保险风险分析 Demo

面向课程投标汇报的单仓库原型：用玉米期货行情做价格基线，连接保险赔付情景，并支持农户、合作社、保险机构和农业管理部门视角。当前默认确定性模拟行情并明确标识；配置 UQER 后尝试真实行情，SDK/API 不可用则返回有标记的模拟兜底数据。

## 本地开发

```bash
cd backend
uv sync --extra dev
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Python 使用 3.12（与后端镜像一致），先验证解释器版本，再创建虚拟环境。前端使用 Node.js 22：另开终端执行 `source ~/.nvm/nvm.sh && cd frontend && nvm use && npm ci && npm run dev`。浏览器访问 `http://localhost:5173`，API 文档位于 `http://localhost:8000/docs`。

后端代码提交前，在 `backend` 目录运行 `uv run --extra dev ruff format app tests` 格式化代码，并运行 `uv run --extra dev ruff check app tests` 检查 lint 规则。

GitHub Actions 会在每次 push 和 Pull Request 上运行相同的 Ruff 格式与 lint 检查。要阻止未通过检查的变更合入受保护分支，请在仓库 **Settings → Rules → Rulesets**（或 **Branches**）中为目标分支启用 Pull Request 与 required status check，并选择 **Backend Ruff / Ruff**。该检查在首次运行前不会出现在可选检查列表中。

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

部署环境需要安装 Docker Compose，并准备运行所需的 `.env`（例如 `UQER_TOKEN`）。`pull_policy: never` 让 Compose 使用本机已导入的镜像，不尝试从镜像仓库拉取。构建环境和部署环境的 CPU 架构需兼容；例如 ARM 镜像不能直接在常见的 x86_64 环境运行。

## VS Code 一键本地启动

1. 在项目根目录准备 `.env`（首次可复制 `.env.example`），令牌只写在 `.env` 的 `UQER_TOKEN` 中；`.env` 已被 Git 忽略。
2. 按上面的本地开发步骤使用 `uv sync --extra dev` 创建 `backend/.venv` 并安装依赖；在 `frontend` 执行 `npm install`。
3. 用 VS Code 打开项目根目录，安装 Python/Python Debugger 扩展；在“运行和调试”选择 **Corn Risk Demo: Local Development**，按 F5 同时启动前后端。

前端：`http://127.0.0.1:5173`；后端：`http://127.0.0.1:8000/docs`。调试配置从根目录 `.env` 注入后端环境变量；不要把 `.env` 提交到 Git。

## 可选 UQER

复制 `.env.example` 为 `.env` 并配置 `DATA_PROVIDER=uqer`、`UQER_TOKEN`。在有权访问 UQER SDK 的环境中执行 `uv sync --extra uqer` 安装可选依赖；适配器使用 UQER SDK 的公开调用方式：`uqer.Client(token=...)` 后调用 `DataAPI.MktFutdGet(..., exchangeCD="XDCE", contractObject="c", pandas="1")`。密钥仅通过环境变量传入，严禁提交、打入镜像或记录日志。无法访问 SDK 时 Demo 会使用标注后的 mock 数据。

## Demo 路径与业务边界

1. 切换四类角色，查看个人保单、合作社成员、保险机构承保与理赔、农业管理部门区域项目。业务台账使用关联的 Mock 数据，首页指标由台账汇总。
2. 农户提交模拟理赔申请，保险机构审核并模拟支付；各角色赔付统计同步更新。合作社可为未参保成员建立模拟保单，管理部门可查看覆盖情况、模拟拨付补贴。
3. 台账支持搜索、状态/地区筛选、详情和 CSV 导出。模拟操作保存在本机浏览器，刷新保留，可确认重置。
4. 从保单详情带入试算，或在独立试算页调整保障价、情景价、免赔额、数量与上限；各角色分别保留会话输入，试算不修改台账。
5. 行情和参考估计位于辅助页面。农业管理部门首页以覆盖率、补贴执行、赔付兑现及项目跟进为核心。

角色切换仅为演示，不构成身份认证或数据权限隔离。

示例公式：`赔付 = min(max(保障价 - 结算价 - 每吨免赔额, 0) × 承保吨数, 赔付上限)`。这只是演示规则；实际实现必须遵循合同规定的价格来源、基差、触发、费率、赔付上限和结算日。期货价不等于保单结算价，预测不等于实际赔付，演示模型不用于投保决策。

## 架构

- `backend/app/api`: HTTP 路由与请求 schema
- `backend/app/domain`: 不依赖框架的保险领域计算
- `backend/app/services`: 用例编排
- `backend/app/adapters`: UQER 和模拟数据适配层
- `frontend`: Vue 3 + TypeScript + Vite 单页应用
- `docs`: 系统架构和后续迭代路线
