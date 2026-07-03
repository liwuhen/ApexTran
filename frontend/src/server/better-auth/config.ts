import { betterAuth } from "better-auth";
import Database from "better-sqlite3";

export const auth = betterAuth({
  // 本地用 SQLite 文件存 user/session/account 表;路径可用 env 覆盖。
  database: new Database(process.env.AUTH_DB_PATH ?? "./auth.db"),

  emailAndPassword: {
    enabled: true,
    // 开发期先关邮箱验证,跑通后再开。
    requireEmailVerification: false,
  },
});

export type Session = typeof auth.$Infer.Session;
