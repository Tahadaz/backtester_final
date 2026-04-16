export function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ""
  let inQuotes = false

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]

    if (inQuotes) {
      if (ch === "\"") {
        const next = text[i + 1]
        if (next === "\"") {
          field += "\""
          i += 1
        } else {
          inQuotes = false
        }
      } else {
        field += ch
      }
      continue
    }

    if (ch === "\"") {
      inQuotes = true
      continue
    }
    if (ch === ",") {
      row.push(field)
      field = ""
      continue
    }
    if (ch === "\n") {
      row.push(field)
      rows.push(row)
      row = []
      field = ""
      continue
    }
    if (ch === "\r") {
      continue
    }
    field += ch
  }

  row.push(field)
  rows.push(row)
  return rows.filter((r) => !(r.length === 1 && r[0] === ""))
}

export function parseCsvRecords(text: string): Array<Record<string, string>> {
  const rows = parseCsv(text)
  if (!rows.length) return []

  const headers = rows[0]
  const out: Array<Record<string, string>> = []
  for (let i = 1; i < rows.length; i += 1) {
    const record: Record<string, string> = {}
    const values = rows[i]
    for (let j = 0; j < headers.length; j += 1) {
      record[headers[j] ?? `col_${j}`] = values[j] ?? ""
    }
    out.push(record)
  }
  return out
}
