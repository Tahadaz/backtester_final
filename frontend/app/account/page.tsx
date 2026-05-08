import { auth, signOut } from "@/auth"
import { redirect } from "next/navigation"

export default async function AccountPage() {
  const session = await auth()
  if (!session?.user) redirect("/login")

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Mon compte</h1>
          <p className="text-sm text-muted-foreground">{session.user.email}</p>
        </div>

        <form
          action={async () => {
            "use server"
            await signOut({ redirectTo: "/login" })
          }}
        >
          <button
            type="submit"
            className="w-full rounded-md border border-input px-4 py-2 text-sm font-medium shadow-sm hover:bg-accent"
          >
            Se déconnecter
          </button>
        </form>
      </div>
    </div>
  )
}
