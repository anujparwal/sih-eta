# Frontend

Follow the root guide. Use Next.js App Router, strict TypeScript and Tailwind
CSS 4 through `@tailwindcss/postcss`. Phase 1 renders a static scaffold page;
passenger, station and control functionality belongs to Phase 6.

Use semantic HTML, visible keyboard focus for future controls and responsive
layouts. Do not fabricate live data. Avoid fonts/assets that require network
access during builds. Keep `package-lock.json` committed; use `npm ci`.
Run `npm run lint`, `npm run typecheck` and `npm run build` here before finishing.

`NEXT_PUBLIC_API_BASE_URL` is browser-visible and fixed at build time. Use
`API_INTERNAL_URL` only in future server-side code; Compose service hostnames
are not reachable from the user's browser. Never place secrets in public vars.
