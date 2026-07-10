/**
 * Private market BFF proxy.
 *
 * Browser code calls /api/market/* with the better-auth cookie. This handler
 * validates the session, signs a short-lived internal JWT for apextran-app, and
 * forwards the request to /api/v1/market/*. It never stores market business data.
 */
import { type NextRequest, NextResponse } from "next/server";

import { auth } from "@/server/better-auth/config";
import { signInternalJwt } from "@/server/internal-auth/jwt";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const INTERNAL_URL =
  process.env.DEER_FLOW_INTERNAL_APP_BASE_URL ?? "http://127.0.0.1:8100";

const STRIP_REQUEST = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "keep-alive",
  "upgrade",
  "authorization",
  "x-apextran-user",
  "x-apextran-proxy-secret",
]);
const STRIP_RESPONSE = new Set([
  "connection",
  "content-length",
  "content-encoding",
  "transfer-encoding",
  "keep-alive",
]);

function scopesForMethod(method: string) {
  const scopes = ["market:read", "market:watchlists:read"];
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    scopes.push("market:watchlists:write");
  }
  return scopes;
}

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const session = await auth.api.getSession({ headers: request.headers });
  const userId = session?.user?.id;
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIP_REQUEST.has(key.toLowerCase())) headers.set(key, value);
  });
  let token: string;
  try {
    token = signInternalJwt({
      userId,
      scopes: scopesForMethod(request.method),
    });
  } catch {
    return NextResponse.json(
      { error: "internal jwt is not configured" },
      { status: 500 },
    );
  }
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Cache-Control", "no-store");

  const suffix = path.length > 0 ? `/${path.join("/")}` : "";
  const url = `${INTERNAL_URL.replace(/\/+$/, "")}/api/v1/market${suffix}${request.nextUrl.search}`;
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
  respHeaders.set("Cache-Control", "no-store");

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
