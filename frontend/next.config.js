/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

function getInternalServiceURL(envKey, fallbackURL) {
  const configured = process.env[envKey]?.trim();
  return configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : fallbackURL;
}
/** @type {import("next").NextConfig} */
const config = {
  devIndicators: false,
  // 关闭 gzip 压缩:否则代理的 SSE(text/event-stream)会被 gzip 缓冲,
  // 导致流式输出在浏览器里变成"一次性"出现。前端直连后端、无 nginx,关掉最简单。
  compress: false,
  // 原生模块不参与打包(better-auth 在服务端用它),避免 dev 编译负担与内存占用。
  serverExternalPackages: ["better-sqlite3"],
  experimental: {
    // 把这些重依赖的桶文件改成按需导入:dev 首屏只编译真正用到的子模块,
    // 大幅降低模块图规模与编译内存峰值(卡死主因是首屏编译把内存打爆)。
    optimizePackageImports: [
      "lucide-react",
      "@radix-ui/react-icons",
      "codemirror",
      "@uiw/react-codemirror",
      "@codemirror/language-data",
      "katex",
      "shiki",
      "@xyflow/react",
      "date-fns",
      "motion",
    ],
  },
  async rewrites() {
    const rewrites = [];
    // ApexTran serves both the LangGraph-compatible runtime and the gateway
    // resource API from a single WebChannel (default 127.0.0.1:8000). There is
    // no nginx in front, so the frontend proxies /api/* to it directly here.
    const gatewayURL = getInternalServiceURL(
      "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL",
      "http://127.0.0.1:8000",
    );

    // apextran-app business microservice (market data + analysis). In the nginx
    // stack /api/v1/* is routed to it by nginx; this rewrite makes the same
    // paths work when the frontend is hit directly on :3000 (plain `next dev`).
    // Public market data needs no auth, so a straight proxy is fine here.
    const appURL = getInternalServiceURL(
      "DEER_FLOW_INTERNAL_APP_BASE_URL",
      "http://127.0.0.1:8100",
    );
    rewrites.push({
      source: "/api/v1/:path*",
      destination: `${appURL}/api/v1/:path*`,
    });

    // 注意:/api/langgraph/* 不再用 rewrite,而是由服务端 BFF route handler
    // (src/app/api/langgraph/[...path]/route.ts)独占——它在转发前校验 better-auth
    // 会话并注入受信租户身份 X-ApexTran-User。用 rewrite 会绕过鉴权,故移除。

    if (!process.env.NEXT_PUBLIC_BACKEND_BASE_URL) {
      // Forward gateway resource endpoints, keeping the /api prefix. These are
      // listed explicitly (not a broad /api/:path*) because afterFiles rewrites
      // take precedence over dynamic routes — a catch-all would hijack
      // Next-local routes like /api/auth/[...all] and /api/memory and break
      // auth. Add new gateway paths here as later milestones implement them.
      for (const p of ["models", "skills"]) {
        rewrites.push({
          source: `/api/${p}`,
          destination: `${gatewayURL}/api/${p}`,
        });
        rewrites.push({
          source: `/api/${p}/:path*`,
          destination: `${gatewayURL}/api/${p}/:path*`,
        });
      }
    }

    return rewrites;
  },
};

export default config;
