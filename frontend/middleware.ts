import NextAuth from "next-auth"
import authConfig from "@/auth.config"

const { auth } = NextAuth(authConfig)

export default auth

export const config = {
  // During parallel A/B development, /v1 is intentionally excluded so the
  // dashboard remains accessible without login in the A-workstream chat.
  // Remove "v1|" once A.3 is merged and auth is fully wired.
  matcher: ["/((?!v1|api/auth|_next/static|_next/image|login|signup|favicon.ico|public).*)"],
}
