import Link from "next/link"

export default function PendingPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-4 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Demande envoyée</h1>
        <p className="text-sm text-muted-foreground">
          Votre compte est en attente d&apos;activation par l&apos;administrateur. Vous recevrez
          une confirmation dès que votre accès sera approuvé.
        </p>
        <Link href="/login" className="text-sm underline underline-offset-4 hover:text-primary">
          Retour à la connexion
        </Link>
      </div>
    </div>
  )
}
