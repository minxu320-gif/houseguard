# HouseGuard 架构说明（比赛 / 生产向）

## 1. 项目结构（分层）

| 层级 | 路径 | 职责 |
|------|------|------|
| **Views** | `houses/views.py` | HTTP：鉴权、重定向、调用 service、选择模板 |
| **Services** | `houses/services/` | 业务规则：风控 `risk_service` / `risk_analytics_service`、匹配、信用、**`dashboard_service`** |
| **Repositories** | `houses/repositories/` | 可复用查询构造（如 `RiskAlertRepository`） |
| **API** | `houses/api/` | 无 DRF 的 JSON 端点，复用 services，便于未来小程序 / SPA |
| **Utils** | `houses/utils/` | 横切能力（日志等） |
| **Templates** | `houses/templates/houses/dashboard|auth|risk/` | 按模块拆分页面 |
| **Constants** | `houses/constants.py` | 风险等级、分页默认值等 |

原则：**views 不写复杂业务**；列表统计用 **聚合 + 分页**，避免全表载入。

## 2. 安全与配置

- `DEBUG` 默认 **关闭**；`SECRET_KEY`、`ALLOWED_HOSTS` 在非调试模式下 **强制环境变量**。
- `MYSQL_PASSWORD` **禁止代码默认值**；未设置则 `ImproperlyConfigured`。
- `manage.py test` 使用 **内存 SQLite**，无需 MySQL。
- Session / CSRF：`HttpOnly`、`SameSite`；可按 `DJANGO_SESSION_COOKIE_SECURE` 控制 HTTPS Cookie。
- 反向代理 HTTPS：`DJANGO_BEHIND_HTTPS_PROXY=1` 启用 `SECURE_PROXY_SSL_HEADER`。
- 可选 **`REDIS_URL`**：启用 Django `RedisCache`；否则 `LocMemCache`。

详见 `.env.example`。

## 3. 数据库与性能

- **迁移 `0005`**：`RiskAlert.level` 扩至 16 字符以支持 `critical`；`risk_alert` / `house` / `house_task` / `stay_request` 增加组合索引。
- 风险列表：**DB 级 `aggregate(Count)`** + **每页 25 条** `Paginator`，替代 `[:200]` 切片。
- 房主合同区：**`dashboard_service.build_agreements_with_perms`** 批量预取 `StayRequest` / `House`，消除 N+1。

## 4. 风险模块

- 等级：**low / medium / high / critical**（`houses/constants.py`）。
- 规则：`checkin_overdue` ≥48h → **critical**（新 `alert_type` 防与 24h 重复）；任务未完成仍为 **medium**。
- **筛选**：房源 ID、请求 ID、等级、日期范围。
- **趋势**：近 14 日按等级计数（ECharts）。
- **AI 预留**：`ai_risk_score_preview()` 占位，供后续模型替换。

## 5. Docker 一键部署

- **db**：MySQL 8 + healthcheck。
- **redis**：缓存（可选）。
- **web**：Gunicorn + migrate + collectstatic；静态与媒体写入命名卷。
- **nginx**：反代 Gunicorn，**托管 `/static/`、`/media/`**。

根目录：`docker compose up -d --build`（需先配置 `.env`）。

## 6. API 入口

- `GET /houses/api/v1/health/`
- `GET /houses/api/v1/risk/summary/`（需 session 登录）

业务与 B/S 页面共用 `risk_analytics_service`。

## 7. 后续可演进

- 引入 **DRF** + JWT，与现有 session 并存。
- `repositories` 扩展为按聚合根的 **QuerySet** 封装 + 单元测试。
- 将 `views.py` 拆分为 `houses/views/` 包（按资源文件拆分）。
