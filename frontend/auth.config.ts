import type { NextAuthConfig } from "next-auth"

const authConfig = {
  session: { strategy: "jwt" },
  trustHost: true,
  pages: {
    signIn: "/login",
  },
  callbacks: {
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
