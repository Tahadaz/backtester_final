import { SignalsHeader } from "@/components/signals-header"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"
const hideWorkspaceNavItems = process.env.HIDE_WORKSPACE_NAV_ITEMS === "true"

export async function DynamicHeader() {
  if (isPublicDashboardOnly) {
    return <SignalsHeader sessionEmail={null} hideWorkspaceNavItems={hideWorkspaceNavItems} />
  }

  const { auth } = await import("@/auth")
  const session = await auth()

  return <SignalsHeader sessionEmail={session?.user?.email ?? null} hideWorkspaceNavItems={hideWorkspaceNavItems} />
}
