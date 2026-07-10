# apextran-app — 业务微服务

除 `agent-service`(`backend`)外**唯一**的业务微服务。内部按功能分模块
(`market`、`analysis`、未来的 `B`/`C`…),模块共享进程与基建,整体部署。

完整设计见 [`docs/business-service-架构方案.md`](../../docs/business-service-架构方案.md)。

## 运行(M1)

```bash
uv sync                                   # 安装 workspace 依赖(含本服务)
uv run apextran-app serve                 # 启动 API(默认 127.0.0.1:8100)
uv run apextran-app worker                # 启动采集/后台任务(可选,M1 也可只跑 serve)

curl http://127.0.0.1:8100/api/v1/market/hotlist
curl http://127.0.0.1:8100/healthz
open http://127.0.0.1:8100/docs           # 自动 OpenAPI 契约
```

M1 用 `MockMarketSource` + 内存缓存,不依赖 Redis/Centrifugo/Postgres。
`serve` 单进程即可返回数据(缓存未命中时惰性回源);`worker` 负责主动刷新。

## 私有市场数据(PostgreSQL)

未配置 `APP_DB_URL` 时,`market` 自选股仅在开发环境使用进程内过渡存储;
`APP_ENVIRONMENT=prod|production` 会直接拒绝启动。配置 `APP_DB_URL` 后,
`market` 模块会切到 PostgreSQL repository,每个私有请求在事务内设置
`app.user_id` 供 RLS 策略隔离用户数据。

```bash
export APP_MIGRATION_DB_URL='postgresql://apextran_migrator:***@127.0.0.1:5433/apextran'
export APP_DB_URL='postgresql://market_app:***@127.0.0.1:5433/apextran'
export APP_INTERNAL_JWT_SECRET='同 frontend 的 APEXTRAN_INTERNAL_JWT_SECRET'
uv run apextran-app migrate
uv run apextran-app sync-stock-pool
uv run apextran-app serve
```

迁移 SQL 位于 `services/app/migrations/`。`APP_MIGRATION_DB_URL` 使用迁移账号
建表和授权,`APP_DB_URL` 使用低权限运行账号,确保 `market.watchlists` /
`market.watchlist_items` 的 RLS 对运行流量生效。当前落地
`market.stock_instruments`、`market.watchlists`、`market.watchlist_items`
和 RLS。配置数据库后,股票搜索只查 `stock_instruments`;首次上线或定期维护
通过 `uv run apextran-app sync-stock-pool` / worker 的
`APP_STOCK_POOL_REFRESH_INTERVAL` 刷新股票池。`watchlist_items` 只保存用户、
分组、股票身份、排序和备注;实时价格通过 `/api/v1/market/quotes` 读取短缓存并
在前端合并展示。

## 加一个新模块

```
cp -r src/apextran_app/modules/_template src/apextran_app/modules/<name>
# 填 domain/ports/adapters/service/router,写 wiring.py 导出 MODULE
```

`main`/`worker` 会自动发现,无需改装配代码。
