import { config } from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getMigrations } from "better-auth/db";
import { Pool } from "pg";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../..");

config({ path: path.join(repoRoot, ".env"), quiet: true });
config({ path: path.join(repoRoot, "frontend/.env"), override: false, quiet: true });

const databaseUrl =
  process.env.BETTER_AUTH_DATABASE_URL ?? process.env.AUTH_DATABASE_URL;

if (!databaseUrl) {
  throw new Error("BETTER_AUTH_DATABASE_URL or AUTH_DATABASE_URL is required");
}

const pool = new Pool({
  connectionString: databaseUrl,
  options: "-c search_path=auth,public",
});

try {
  const { runMigrations } = await getMigrations({
    database: pool,
    emailAndPassword: {
      enabled: true,
      requireEmailVerification: false,
    },
  });

  await runMigrations();
  console.info("better-auth migrations applied");
} finally {
  await pool.end();
}
