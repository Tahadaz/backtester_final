"use client"

import { PlotlyChart } from "@/components/run/plotly-chart"

export function PlotlyHeatmap({ x, y, z, title = "Parameter heatmap" }: { x: Array<string | number>; y: Array<string | number>; z: Array<Array<number | null>>; title?: string }) {
  return <PlotlyChart figure={{ data: [{ type: "heatmap", x, y, z, colorscale: "RdBu", zmid: 0, colorbar: { title: { text: "Sharpe" } } }], layout: { title: { text: title }, xaxis: { title: { text: "Lookback (mois)" } }, yaxis: { title: { text: "Vol cible" } } } }} />
}
