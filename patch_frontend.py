with open("frontend/app/signals/wfo-detail/page.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# Replace exactly
old_header = """                    <th className="px-3 py-2 text-right font-medium">OOS Return</th>
                    <th className="px-3 py-2 text-left font-medium">Gagnant</th>"""
new_header = """                    <th className="px-3 py-2 text-right font-medium">OOS Return</th>
                    <th className="px-3 py-2 text-right font-medium">OOS Sharpe</th>
                    <th className="px-3 py-2 text-left font-medium">Gagnant</th>"""
content = content.replace(old_header, new_header)

old_row = """                      <td className="px-3 py-2 text-right font-mono">
                        <span className={fold.oos_return > 0 ? "text-green-700" : "text-red-700"}>
                          {(fold.oos_return * 100).toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span className="font-mono text-[10px] text-muted-foreground truncate max-w-[150px] block">
                          {fold.winner_variant_id || "—"}
                        </span>
                      </td>"""
new_row = """                      <td className="px-3 py-2 text-right font-mono">
                        <span className={fold.oos_return > 0 ? "text-green-700" : "text-red-700"}>
                          {(fold.oos_return * 100).toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {fold.oos_sharpe != null ? fold.oos_sharpe.toFixed(2) : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span className="font-mono text-[10px] text-muted-foreground truncate max-w-[150px] block" title={fold.winner_variant_id}>
                          {fold.winner_description || fold.winner_variant_id || "—"}
                        </span>
                      </td>"""
content = content.replace(old_row, new_row)

old_footer = """                  <tr className="border-t-2 bg-secondary/20 font-medium">
                    <td colSpan={3} className="px-3 py-2">Resume</td>
                    <td className="px-3 py-2 text-right font-mono text-[10px]">—</td>
                    <td className="px-3 py-2 text-right font-mono text-[10px]">—</td>
                    <td className="px-3 py-2">"""
new_footer = """                  <tr className="border-t-2 bg-secondary/20 font-medium">
                    <td colSpan={3} className="px-3 py-2">Resume</td>
                    <td className="px-3 py-2 text-right font-mono text-[10px]">—</td>
                    <td className="px-3 py-2 text-right font-mono text-[10px]">—</td>
                    <td className="px-3 py-2 text-right font-mono text-[10px]">—</td>
                    <td className="px-3 py-2">"""
content = content.replace(old_footer, new_footer)

with open("frontend/app/signals/wfo-detail/page.tsx", "w", encoding="utf-8") as f:
    f.write(content)

print("Patch applied properly")
