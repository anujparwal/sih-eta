# Frontend

Follow the root guide. Use Next.js App Router, strict TypeScript and Tailwind
CSS 4 through `@tailwindcss/postcss`. Phase 6 implements passenger, station
and control views. Keep network/telemetry sourced from the backend; test-only
fixtures belong in tests/.

Use semantic HTML, visible keyboard focus for controls and responsive
layouts. Do not fabricate live data. Avoid fonts/assets that require network
access during builds. Keep `package-lock.json` committed; use `npm ci`.
Run `npm run lint`, `npm run typecheck`, `npm run build` and `npm run test:e2e`
here before finishing. See the README for `npm run test:live` prerequisites.

`NEXT_PUBLIC_API_BASE_URL` is browser-visible and fixed at build time. Use
`API_INTERNAL_URL` only in the server-side GET proxy; Compose service hostnames
are not reachable from the user's browser. Never place secrets in public vars.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
