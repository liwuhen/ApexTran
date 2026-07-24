import { betterAuth } from "better-auth";
import Database from "better-sqlite3";
import { Pool } from "pg";

// 仅开发模式信任本地 localhost 来源。触发条件:启动脚本 dev 模式注入 APEXTRAN_DEV=1,
// 或 next dev 下 NODE_ENV=development(即 `make dev`)。生产(next start)不含这些,
// 避免把开发地址带上线;生产只信任 BETTER_AUTH_URL 及可选 BETTER_AUTH_TRUSTED_ORIGINS。
const isDev =
  process.env.APEXTRAN_DEV === "1" || process.env.NODE_ENV !== "production";

const devTrustedOrigins = isDev
  ? [
      "http://localhost:3000",
      "http://127.0.0.1:3000",
      "http://localhost",
      "http://127.0.0.1",
    ]
  : [];

// 额外可信来源(生产按需配置真实域名),与开发来源合并追加。
const extraTrustedOrigins = (process.env.BETTER_AUTH_TRUSTED_ORIGINS ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

function buildDatabase() {
  const databaseUrl =
    process.env.BETTER_AUTH_DATABASE_URL ?? process.env.AUTH_DATABASE_URL;
  if (databaseUrl) {
    return new Pool({
      connectionString: databaseUrl,
      options: "-c search_path=auth,public",
    });
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "BETTER_AUTH_DATABASE_URL or AUTH_DATABASE_URL is required in production",
    );
  }
  return new Database(process.env.AUTH_DB_PATH ?? "./auth.db");
}

export const auth = betterAuth({
  // 生产用 PostgreSQL(auth schema);未配置时仅开发回退 SQLite。
  database: buildDatabase(),

  // baseURL 始终被 better-auth 自动信任;这里只"追加"开发/额外来源。
  trustedOrigins: [...devTrustedOrigins, ...extraTrustedOrigins],

  emailAndPassword: {
    enabled: true,
    // 开发期先关邮箱验证,跑通后再开。
    requireEmailVerification: false,
  },
});

export type Session = typeof auth.$Infer.Session;
