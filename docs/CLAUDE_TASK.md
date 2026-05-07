You need to diagnose why this repo’s app/build/deploy setup is broken and then fix it properly.

Problem:
The project structure feels tangled and unreliable. Docker app/runtime, frontend builds, and GitHub Pages/static publishing may be interfering with each other. Things are “not working properly,” but the exact root cause is unclear.

Your job:
1. Inspect the repo structure, build scripts, Docker files, compose files, frontend config, and GitHub Actions.
2. Find the real structural problems, not just surface errors.
3. Identify what is coupled incorrectly.
4. Implement a clean, durable structure.
5. Remove hacks/workarounds if they are part of the problem.
6. Keep the final architecture easy to understand.

What I care about:
- Docker/runtime should work reliably.
- Static/GitHub Pages publishing should not interfere with runtime.
- Build outputs, env flags, scripts, and routing should be unambiguous.
- Repo structure should be clear enough that future changes don’t keep breaking it.

Deliverables:
- Diagnose root causes.
- Implement fixes directly.
- Keep changes minimal but decisive.
- Brief final summary with:
  - root cause(s)
  - what was changed
  - exact commands to run to verify

Important:
- Do not stop at analysis.
- Do not preserve bad structure just for compatibility if it keeps the repo unstable.
- Prefer the simplest clean architecture after inspecting the repo.
- Be concise and token-efficient.
