import NextAuth from "next-auth"
import authConfig from "@/auth.config"

const { auth } = NextAuth(authConfig)

export default auth

export const config = {
  matcher: ["/((?!v1|api/auth|_next/static|_next/image|login|signup|favicon.ico|.*\\..*).*)"],
}
