import { redirect } from "next/navigation"

type SearchParams = Record<string, string | string[] | undefined>

export default async function FundamentalsRedirect({
  searchParams,
}: {
  searchParams?: SearchParams | Promise<SearchParams>
}) {
  const resolved = await Promise.resolve(searchParams ?? {})
  const params = new URLSearchParams()

  for (const [key, value] of Object.entries(resolved)) {
    if (value == null || key === "mode") continue
    if (Array.isArray(value)) {
      for (const item of value) {
        params.append(key, item)
      }
    } else {
      params.set(key, value)
    }
  }

  params.set("mode", "fundamental")
  redirect(`/signals?${params.toString()}`)
}
