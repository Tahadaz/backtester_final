import test from "node:test"
import assert from "node:assert/strict"

import { filterTradeMarkersByKind, normalizeTradeMarkers } from "./trade-marker-utils.js"

test("normalizeTradeMarkers maps long open and close ledger rows", () => {
  const markers = normalizeTradeMarkers([
    { date: "2026-01-02", side: "ACHAT", position: 1 },
    { date: "2026-01-06", side: "VENTE", position: 0 },
  ])

  assert.deepEqual(markers, [
    { date: "2026-01-02", kind: "buy" },
    { date: "2026-01-06", kind: "sell" },
  ])
})

test("normalizeTradeMarkers maps short open and cover ledger rows", () => {
  const markers = normalizeTradeMarkers([
    { date: "2026-01-02", side: "VENTE", position: -1 },
    { date: "2026-01-06", side: "ACHAT", position: 0 },
  ])

  assert.deepEqual(markers, [
    { date: "2026-01-02", kind: "short" },
    { date: "2026-01-06", kind: "cover" },
  ])
})

test("normalizeTradeMarkers lets explicit marker labels override side inference", () => {
  const markers = normalizeTradeMarkers([
    { date: "2026-01-02T12:00:00Z", side: "ACHAT", position: 0, marker_label: "Buy" },
    { date: "2026-01-03T12:00:00Z", side: "VENTE", position: 1, marker_label: "Cover" },
  ])

  assert.deepEqual(markers, [
    { date: "2026-01-02", kind: "buy", label: "Buy" },
    { date: "2026-01-03", kind: "cover", label: "Cover" },
  ])
})

test("normalizeTradeMarkers handles literal short and cover sides without position", () => {
  const markers = normalizeTradeMarkers([
    { date: "2026-01-02", side: "SHORT" },
    { date: "2026-01-03", side: "COVER" },
  ])

  assert.deepEqual(markers, [
    { date: "2026-01-02", kind: "short" },
    { date: "2026-01-03", kind: "cover" },
  ])
})

test("normalizeTradeMarkers sorts chronologically and preserves same-day ledger order", () => {
  const markers = normalizeTradeMarkers([
    { date: "2026-01-06", side: "VENTE", position: 0 },
    { date: "2026-01-02", side: "ACHAT", position: 1 },
    { date: "2026-01-02", side: "VENTE", position: -1 },
    { date: "2026-01-07", side: "ACHAT", position: 0 },
  ])

  assert.deepEqual(markers, [
    { date: "2026-01-02", kind: "buy" },
    { date: "2026-01-02", kind: "short" },
    { date: "2026-01-06", kind: "sell" },
    { date: "2026-01-07", kind: "cover" },
  ])
})

test("normalizeTradeMarkers skips rows without usable dates or sides", () => {
  const markers = normalizeTradeMarkers([
    { date: "not-a-date", side: "ACHAT", position: 1 },
    { date: "2026-01-02", side: "NEUTRE", position: 0 },
    { timestamp: "2026-01-03T09:30:00Z", side: "VENTE", position: 0 },
  ])

  assert.deepEqual(markers, [
    { date: "2026-01-03", kind: "sell" },
  ])
})

test("filterTradeMarkersByKind keeps only selected marker kinds", () => {
  const markers = normalizeTradeMarkers([
    { date: "2026-01-02", side: "ACHAT", position: 1 },
    { date: "2026-01-03", side: "VENTE", position: -1 },
    { date: "2026-01-04", side: "VENTE", position: 0 },
    { date: "2026-01-05", side: "ACHAT", position: 0 },
  ])

  assert.deepEqual(filterTradeMarkersByKind(markers, ["buy", "cover"]), [
    { date: "2026-01-02", kind: "buy" },
    { date: "2026-01-05", kind: "cover" },
  ])
})

test("filterTradeMarkersByKind hides all markers when no kinds are visible", () => {
  assert.deepEqual(
    filterTradeMarkersByKind([{ date: "2026-01-02", kind: "buy" }], []),
    [],
  )
})
