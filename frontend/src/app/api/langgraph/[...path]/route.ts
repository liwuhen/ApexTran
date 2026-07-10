/**
 * BFF 代理:前端服务端把浏览器发往 `/api/langgraph/*` 的 LangGraph 请求转发到后端
 * WebChannel,并在此**唯一可信入口**注入租户身份:
 *
 *  - 在服务端校验 better-auth 会话,取出 `user.id`,以 `X-ApexTran-User` 注入。
 *    浏览器无法伪造它——请求到不了后端,只能经过这一层。
 *  - 可选地带上 `X-ApexTran-Proxy-Secret`(与后端 `ApexTran_WEB_PROXY_SECRET` 对齐),
 *    这样即便后端端口被直连也无法冒充他人。
 *  - 响应体**流式直通**(`response.body`),绝不缓冲——否则 SSE(runs/stream)会失效。
 */
import { type NextRequest, NextResponse } from "next/server";

import { auth } from "@/server/better-auth/config";

// better-sqlite3 是原生模块,必须走 Node 运行时;且禁用缓存。
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const INTERNAL_URL =
  process.env.DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL ?? "http://127.0.0.1:8000";
const PROXY_SECRET = process.env.ApexTran_WEB_PROXY_SECRET ?? "";
// 未登录是否拒绝(C 端量产建议开启;本地开发默认放行为 "default")。
const REQUIRE_AUTH = process.env.APEXTRAN_REQUIRE_AUTH === "1";

// hop-by-hop 头不能透传;content-encoding/length 因 fetch 已解码而失真,需剔除。
const STRIP_REQUEST = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "keep-alive",
  "upgrade",
]);
const STRIP_RESPONSE = new Set([
  "connection",
  "content-length",
  "content-encoding",
  "transfer-encoding",
  "keep-alive",
]);

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const isHealthCheck = request.method === "GET" && path.join("/") === "health";
  let userId: string | undefined;
  if (!isHealthCheck) {
    try {
      const session = await auth.api.getSession({ headers: request.headers });
      userId = session?.user?.id;
    } catch {
      userId = undefined;
    }
  }

  if (!userId && REQUIRE_AUTH && !isHealthCheck) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIP_REQUEST.has(key.toLowerCase())) headers.set(key, value);
  });
  // 受信身份由服务端注入;显式清掉客户端可能伪造的同名头后再设置。
  headers.set("X-ApexTran-User", userId ?? "default");
  if (PROXY_SECRET) headers.set("X-ApexTran-Proxy-Secret", PROXY_SECRET);

  const suffix = path.length > 0 ? `/${path.join("/")}` : "";
  const url = `${INTERNAL_URL}${suffix}${request.nextUrl.search}`;

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const upstream = await fetch(url, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    redirect: "manual",
  });

  const respHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIP_RESPONSE.has(key.toLowerCase())) respHeaders.set(key, value);
  });

  // 流式直通:SSE / 分块响应逐帧透传,不缓冲。
  return new Response(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
}

type Ctx = { params: Promise<{ path: string[] }> };
const handle = async (request: NextRequest, ctx: Ctx) =>
  proxy(request, (await ctx.params).path ?? []);

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const OPTIONS = handle;
