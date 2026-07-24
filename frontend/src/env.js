import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  /**
   * Specify your server-side environment variables schema here. This way you can ensure the app
   * isn't built with invalid env vars.
   */
  server: {
    BETTER_AUTH_SECRET:
      process.env.NODE_ENV === "production"
        ? z.string()
        : z.string().optional(),
    BETTER_AUTH_GITHUB_CLIENT_ID: z.string().optional(),
    BETTER_AUTH_GITHUB_CLIENT_SECRET: z.string().optional(),
    BETTER_AUTH_URL: z.string().optional(),
    BETTER_AUTH_BASE_URL: z.string().optional(),
    BETTER_AUTH_TRUSTED_ORIGINS: z.string().optional(),
    BETTER_AUTH_DATABASE_URL: z.string().optional(),
    AUTH_DATABASE_URL: z.string().optional(),
    AUTH_DB_PATH: z.string().optional(),
    APEXTRAN_INTERNAL_JWT_SECRET: z.string().optional(),
    APEXTRAN_INTERNAL_JWT_ISSUER: z.string().optional(),
    APEXTRAN_INTERNAL_JWT_AUDIENCE: z.string().optional(),
    APEXTRAN_INTERNAL_JWT_KEY_ID: z.string().optional(),
    DEER_FLOW_INTERNAL_APP_BASE_URL: z.string().optional(),
    GITHUB_OAUTH_TOKEN: z.string().optional(),
    NODE_ENV: z
      .enum(["development", "test", "production"])
      .default("development"),
  },

  /**
   * Specify your client-side environment variables schema here. This way you can ensure the app
   * isn't built with invalid env vars. To expose them to the client, prefix them with
   * `NEXT_PUBLIC_`.
   */
  client: {
    NEXT_PUBLIC_BACKEND_BASE_URL: z.string().optional(),
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: z.string().optional(),
    NEXT_PUBLIC_STATIC_WEBSITE_ONLY: z.string().optional(),
  },

  /**
   * You can't destruct `process.env` as a regular object in the Next.js edge runtimes (e.g.
   * middlewares) or client-side so we need to destruct manually.
   */
  runtimeEnv: {
    BETTER_AUTH_SECRET: process.env.BETTER_AUTH_SECRET,
    BETTER_AUTH_GITHUB_CLIENT_ID: process.env.BETTER_AUTH_GITHUB_CLIENT_ID,
    BETTER_AUTH_GITHUB_CLIENT_SECRET:
      process.env.BETTER_AUTH_GITHUB_CLIENT_SECRET,
    BETTER_AUTH_URL: process.env.BETTER_AUTH_URL,
    BETTER_AUTH_BASE_URL: process.env.BETTER_AUTH_BASE_URL,
    BETTER_AUTH_TRUSTED_ORIGINS: process.env.BETTER_AUTH_TRUSTED_ORIGINS,
    BETTER_AUTH_DATABASE_URL: process.env.BETTER_AUTH_DATABASE_URL,
    AUTH_DATABASE_URL: process.env.AUTH_DATABASE_URL,
    AUTH_DB_PATH: process.env.AUTH_DB_PATH,
    APEXTRAN_INTERNAL_JWT_SECRET: process.env.APEXTRAN_INTERNAL_JWT_SECRET,
    APEXTRAN_INTERNAL_JWT_ISSUER: process.env.APEXTRAN_INTERNAL_JWT_ISSUER,
    APEXTRAN_INTERNAL_JWT_AUDIENCE: process.env.APEXTRAN_INTERNAL_JWT_AUDIENCE,
    APEXTRAN_INTERNAL_JWT_KEY_ID: process.env.APEXTRAN_INTERNAL_JWT_KEY_ID,
    DEER_FLOW_INTERNAL_APP_BASE_URL:
      process.env.DEER_FLOW_INTERNAL_APP_BASE_URL,
    NODE_ENV: process.env.NODE_ENV,

    NEXT_PUBLIC_BACKEND_BASE_URL: process.env.NEXT_PUBLIC_BACKEND_BASE_URL,
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL,
    NEXT_PUBLIC_STATIC_WEBSITE_ONLY:
      process.env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY,
    GITHUB_OAUTH_TOKEN: process.env.GITHUB_OAUTH_TOKEN,
  },
  /**
   * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially
   * useful for Docker builds.
   */
  skipValidation: !!process.env.SKIP_ENV_VALIDATION,
  /**
   * Makes it so that empty strings are treated as undefined. `SOME_VAR: z.string()` and
   * `SOME_VAR=''` will throw an error.
   */
  emptyStringAsUndefined: true,
});
