import type { NextAuthConfig } from "next-auth"

const authRequired =
  process.env.AUTH_REQUIRED == null
    ? process.env.NODE_ENV === "production" && process.env.NEXT_BUILD_TARGET !== "pages"
    : process.env.AUTH_REQUIRED === "true"

const authConfig = {
  session: {
    strategy: "jwt",
    maxAge: 60 * 60 * 24 * 30,
  },
  trustHost: true,
  pages: {
    signIn: "/login",
  },
  callbacks: {
    authorized: ({ auth }) => !authRequired || Boolean(auth?.user),
    jwt: ({ token, user }) => {
      if (user) token.uid = user.id
      return token
    },
    session: ({ session, token }) => {
      session.user.id = token.uid as string
      return session
    },
  },
  providers: [],
} satisfies NextAuthConfig

export default authConfig
