// Runs once on server startup (Next.js instrumentation hook).
// Creates auth tables if they don't exist — idempotent via IF NOT EXISTS.
export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return
  if (!process.env.DATABASE_URL) return

  const { Pool } = await import("pg")
  const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 1 })
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS users (
        id            TEXT PRIMARY KEY,
        name          TEXT,
        email         TEXT NOT NULL UNIQUE,
        "emailVerified" TIMESTAMPTZ,
        image         TEXT,
        "passwordHash" TEXT,
        "isActive"    BOOLEAN NOT NULL DEFAULT FALSE
      );

      CREATE TABLE IF NOT EXISTS accounts (
        "userId"          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        type              TEXT NOT NULL,
        provider          TEXT NOT NULL,
        "providerAccountId" TEXT NOT NULL,
        refresh_token     TEXT,
        access_token      TEXT,
        expires_at        INTEGER,
        token_type        TEXT,
        scope             TEXT,
        id_token          TEXT,
        session_state     TEXT,
        PRIMARY KEY (provider, "providerAccountId")
      );

      CREATE TABLE IF NOT EXISTS sessions (
        "sessionToken" TEXT PRIMARY KEY,
        "userId"       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires        TIMESTAMPTZ NOT NULL
      );

      CREATE TABLE IF NOT EXISTS "verificationTokens" (
        identifier TEXT NOT NULL,
        token      TEXT NOT NULL,
        expires    TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (identifier, token)
      );
    `)
  } finally {
    await pool.end()
  }
}
