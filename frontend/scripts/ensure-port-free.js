#!/usr/bin/env node

const net = require("node:net")

const port = Number(process.argv[2] ?? process.env.PORT ?? "3000")

if (!Number.isInteger(port) || port <= 0 || port > 65535) {
  console.error(`Invalid port: ${process.argv[2] ?? process.env.PORT}`)
  process.exit(1)
}

function canConnect(host) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port })
    socket.setTimeout(500)
    socket.once("connect", () => {
      socket.destroy()
      resolve(true)
    })
    socket.once("timeout", () => {
      socket.destroy()
      resolve(false)
    })
    socket.once("error", () => {
      resolve(false)
    })
  })
}

function tryBind() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once("error", reject)
    server.once("listening", () => {
      server.close(() => resolve())
    })
    server.listen({ host: "0.0.0.0", port })
  })
}

function reportOccupied() {
  console.error(
    [
      `Port ${port} is already in use.`,
      "Stop the existing frontend before starting another one.",
      "This repo intentionally does not fall back to 3001.",
    ].join("\n"),
  )
}

async function main() {
  for (const host of ["127.0.0.1", "::1"]) {
    if (await canConnect(host)) {
      reportOccupied()
      process.exit(1)
    }
  }

  try {
    await tryBind()
  } catch (error) {
    if (error && error.code === "EADDRINUSE") {
      reportOccupied()
      process.exit(1)
    }
    throw error
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error))
  process.exit(1)
})
