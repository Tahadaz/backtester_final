import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"
import { DrizzleAdapter } from "@auth/drizzle-adapter"
import { eq } from "drizzle-orm"
import bcrypt from "bcryptjs"
import { z } from "zod"
import authConfig from "@/auth.config"
import { db } from "./db"
import { users, accounts, sessions, verificationTokens } from "./schema"

const relaxedLocalCredentials =
  process.env.LOCAL_AUTH_ALLOW_USERNAME_PASSWORD === "true" ||
  (process.env.AUTH_REQUIRED == null
    ? process.env.NODE_ENV !== "production" || process.env.NEXT_BUILD_TARGET === "pages"
    : process.env.AUTH_REQUIRED !== "true")

const CredsSchema = z.object({
  email: relaxedLocalCredentials ? z.string().trim().min(1) : z.string().trim().email(),
  password: z.string().min(relaxedLocalCredentials ? 1 : 8),
})

export const { auth, handlers, signIn, signOut } = NextAuth({
  ...authConfig,
  adapter: DrizzleAdapter(db, {
    usersTable: users,
    accountsTable: accounts,
    sessionsTable: sessions,
    verificationTokensTable: verificationTokens,
  }),
  providers: [
    Credentials({
      credentials: { email: {}, password: {} },
      authorize: async (raw) => {
        const parsed = CredsSchema.safeParse(raw)
        if (!parsed.success) return null
        const user = await db.query.users.findFirst({
          where: eq(users.email, parsed.data.email),
        })
        if (!user?.passwordHash || !user.isActive) return null
        const ok = await bcrypt.compare(parsed.data.password, user.passwordHash)
        return ok ? { id: user.id, email: user.email } : null
      },
    }),
  ],
})
