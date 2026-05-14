import { auth } from "@/auth"
import { redirect } from "next/navigation"

import { OpsClient } from "./ops-client"

function adminEmails(): Set<string> {
  return new Set(
    (process.env.ADMIN_EMAILS ?? "")
      .split(",")
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean),
  )
}

function isAdminEmail(email: string | null | undefined): boolean {
  const normalized = email?.trim().toLowerCase()
  return Boolean(normalized && adminEmails().has(normalized))
}

async function requireAdmin() {
  const session = await auth()
  const userId = session?.user?.id
  const email = session?.user?.email
  if (!userId || !email || !isAdminEmail(email)) {
    redirect("/dashboard")
  }
  return { user: { id: userId, email } }
}

export default async function AdminOpsPage() {
  const session = await requireAdmin()
  return <OpsClient adminEmail={session.user.email} />
}
