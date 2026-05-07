export function buildWfoDetailHref({ symbol, horizon, category, variant = "expanded" }) {
  const params = new URLSearchParams({
    symbol,
    horizon,
    category,
    variant,
  })
  return `/signals/wfo-detail?${params.toString()}`
}
