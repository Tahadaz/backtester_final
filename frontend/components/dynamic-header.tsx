import { SignalsHeader } from "@/components/signals-header"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"
const hideWorkspaceNavItems = process.env.HIDE_WORKSPACE_NAV_ITEMS === "true"

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

export async function DynamicHeader() {
  if (isPublicDashboardOnly) {
    return <SignalsHeader sessionEmail={null} hideWorkspaceNavItems={hideWorkspaceNavItems} />
  }

  const { auth } = await import("@/auth")
  const session = await auth()
  const email = session?.user?.email ?? null

  return <SignalsHeader sessionEmail={email} hideWorkspaceNavItems={hideWorkspaceNavItems} isAdmin={isAdminEmail(email)} />
}
