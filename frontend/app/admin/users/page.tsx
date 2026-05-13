import { auth } from "@/auth"
import { db } from "@/auth/db"
import { users } from "@/auth/schema"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { asc, eq } from "drizzle-orm"
import { redirect } from "next/navigation"
import { revalidatePath } from "next/cache"

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

async function setUserActive(formData: FormData) {
  "use server"

  const session = await requireAdmin()
  const userId = String(formData.get("userId") ?? "")
  const active = String(formData.get("active") ?? "") === "true"
  if (!userId) return
  if (!active && userId === session.user.id) return

  await db.update(users).set({ isActive: active }).where(eq(users.id, userId))
  revalidatePath("/admin/users")
}

export default async function AdminUsersPage() {
  const session = await requireAdmin()
  const rows = await db
    .select({
      id: users.id,
      email: users.email,
      name: users.name,
      isActive: users.isActive,
      emailVerified: users.emailVerified,
    })
    .from(users)
    .orderBy(asc(users.isActive), asc(users.email))

  const pendingUsers = rows.filter((user) => !user.isActive)
  const activeUsers = rows.filter((user) => user.isActive)

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">User approvals</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Signed in as {session.user.email}. New registrations stay pending until approved here.
        </p>
      </div>

      <UserTable
        title="Pending requests"
        emptyText="No pending registration requests."
        users={pendingUsers}
        actionLabel="Approve"
        nextActiveState
      />

      <UserTable
        title="Active users"
        emptyText="No active users."
        users={activeUsers}
        actionLabel="Revoke"
        nextActiveState={false}
        currentUserId={session.user.id}
      />
    </div>
  )
}

function UserTable({
  title,
  emptyText,
  users: rows,
  actionLabel,
  nextActiveState,
  currentUserId,
}: {
  title: string
  emptyText: string
  users: Array<{
    id: string
    email: string
    name: string | null
    isActive: boolean
    emailVerified: Date | null
  }>
  actionLabel: string
  nextActiveState: boolean
  currentUserId?: string
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{emptyText}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Email</th>
                  <th className="py-2 pr-4 font-medium">Name</th>
                  <th className="py-2 pr-4 font-medium">Email verified</th>
                  <th className="py-2 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((user) => {
                  const isSelf = currentUserId === user.id
                  return (
                    <tr key={user.id} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-medium">{user.email}</td>
                      <td className="py-2 pr-4 text-muted-foreground">{user.name ?? "-"}</td>
                      <td className="py-2 pr-4 text-muted-foreground">
                        {user.emailVerified ? user.emailVerified.toISOString().slice(0, 10) : "-"}
                      </td>
                      <td className="py-2 text-right">
                        <form action={setUserActive}>
                          <input type="hidden" name="userId" value={user.id} />
                          <input type="hidden" name="active" value={String(nextActiveState)} />
                          <Button type="submit" variant={nextActiveState ? "default" : "outline"} size="sm" disabled={isSelf}>
                            {isSelf ? "Current admin" : actionLabel}
                          </Button>
                        </form>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
