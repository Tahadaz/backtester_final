import { redirect } from "next/navigation"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"

export default function HomePage() {
  if (isPublicDashboardOnly) {
    redirect("/v1")
  }

  redirect("/dashboard")
}
