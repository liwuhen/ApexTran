# ApexTran Frontend

全量移植自 [deer-flow](https://github.com/bytedance/deer-flow) 的前端(Next.js 16 +
React 19 工作台:聊天、线程、Agent、技能、记忆、设置、文档/博客)。

> **状态**:前端代码已全量移植并能构建(`pnpm build` 通过,48 条路由)。
> **后端尚未对接** —— ApexTran 的 Web 网关还在实现中,见 `../docs/web-gateway-design.md`。
> 在网关就绪前,只有 **mock 模式**(`/mock/api/*`)的静态界面可浏览,实时聊天不可用。

## 技术栈

Next.js 16(App Router, Turbopack)· React 19 · TypeScript · Tailwind v4 ·
shadcn/ui · `@langchain/langgraph-sdk`(`useStream`)· better-auth · nextra(文档/博客)。

## 依赖与运行

本项目用 **pnpm**(锁文件来自 deer-flow,保证版本一致)。环境没有全局 pnpm 时用
corepack:

```bash
corepack pnpm install
BETTER_AUTH_SECRET=<至少32位随机串> corepack pnpm dev     # http://localhost:3000
BETTER_AUTH_SECRET=<...> corepack pnpm build              # 生产构建
corepack pnpm typecheck                                   # tsc --noEmit
```

> 构建/启动必须设置 `BETTER_AUTH_SECRET`(env 校验要求);开发可临时
> `SKIP_ENV_VALIDATION=1` 兜底,但建议用真实非默认密钥。

## 与后端的对接(待网关实现)

前端 `next.config.js` 的 `rewrites()` 把请求同源代理到后端:

| 前端前缀           | 默认目标                  | 说明                       |
| ------------------ | ------------------------- | -------------------------- |
| `/api/langgraph/*` | `http://127.0.0.1:2024`   | 运行时:线程 / 运行 / 流式 |
| `/api/agents/*`    | `http://127.0.0.1:8001`   | Gateway REST:模型/技能等   |

ApexTran 计划用**单个 WebChannel** 同时承载这两套前缀(见设计文档),届时把
`DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL` / `DEER_FLOW_INTERNAL_GATEWAY_BASE_URL`
指向该服务即可。前端契约详见 deer-flow 的
`docs/frontend-backend-communication.md`。

## 已知待清理

- `CLAUDE.md` / `AGENTS.md` / `Makefile` / `Dockerfile` 仍是 deer-flow 的副本,
  后续按 ApexTran 实际情况调整。
- 品牌文案、i18n 文案、docs/blog 内容仍为 deer-flow 原文。
- 不被 ApexTran 支持的界面(子 Agent、artifacts、部分 Agent 管理)需在网关
  里降级或在前端用特性开关隐藏。
