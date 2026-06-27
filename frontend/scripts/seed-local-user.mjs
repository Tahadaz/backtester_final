import crypto from "node:crypto"
import bcrypt from "bcryptjs"
import pg from "pg"

const { Client } = pg

const username = process.env.LOCAL_AUTH_USERNAME ?? "taha"
const password = process.env.LOCAL_AUTH_PASSWORD ?? "taha"
const databaseUrl = process.env.DATABASE_URL ?? "postgresql://app:app@localhost:5555/quant"

const client = new Client({ connectionString: databaseUrl })
const passwordHash = await bcrypt.hash(password, 12)

try {
  await client.connect()
  const result = await client.query(
    `
      INSERT INTO users (id, name, email, "passwordHash", "isActive")
      VALUES ($1, $2, $3, $4, true)
      ON CONFLICT (email)
      DO UPDATE SET
        name = EXCLUDED.name,
        "passwordHash" = EXCLUDED."passwordHash",
        "isActive" = true
      RETURNING id, email, "isActive"
    `,
    [crypto.randomUUID(), username, username, passwordHash],
  )

  const user = result.rows[0]
  console.log(`Local auth user ready: ${user.email} (active=${user.isActive})`)
} finally {
  await client.end()
}
