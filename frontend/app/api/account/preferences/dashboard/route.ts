import { NextRequest, NextResponse } from "next/server"
import { eq } from "drizzle-orm"
import { auth } from "@/auth"
import { db } from "@/auth/db"
import { userPreferences } from "@/auth/schema"
import { sanitizeDashboardPreferences } from "@/lib/dashboard-preferences"

export const runtime = "nodejs"

async function currentUserId(): Promise<string | null> {
  const session = await auth()
  return session?.user?.id ?? null
}

export async function GET() {
  const userId = await currentUserId()
  if (!userId) {
    return NextResponse.json({ error: "authenticated user required" }, { status: 401 })
  }

  const rows = await db
    .select({ dashboard: userPreferences.dashboard })
    .from(userPreferences)
    .where(eq(userPreferences.userId, userId))
    .limit(1)

  return NextResponse.json(sanitizeDashboardPreferences(rows[0]?.dashboard))
}

export async function PUT(req: NextRequest) {
  const userId = await currentUserId()
  if (!userId) {
    return NextResponse.json({ error: "authenticated user required" }, { status: 401 })
  }

  const raw = await req.json().catch(() => null)
  const dashboard = sanitizeDashboardPreferences(raw)
  const dashboardRecord = dashboard as unknown as Record<string, unknown>
  const updatedAt = new Date()

  await db
    .insert(userPreferences)
    .values({ userId, dashboard: dashboardRecord, updatedAt })
    .onConflictDoUpdate({
      target: userPreferences.userId,
      set: { dashboard: dashboardRecord, updatedAt },
    })

  return NextResponse.json(dashboard)
}
