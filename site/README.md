# FlakeGuard site

The landing page for [FlakeGuard](../README.md). Vite + React + TypeScript + Tailwind CSS v4.

```sh
npm install
npm run dev      # http://localhost:5173
npm run build    # -> dist/
```

The hero's matrix comes from [`src/data/run.ts`](src/data/run.ts): one real scheduled run of `dask/distributed`
(run 34568247988), all 34 pooled cells with their pass/fail state. The counts and the legend derive from that array,
so the page cannot disagree with the data it is illustrating.

Deployed on Vercel with **Root Directory** set to `site` — the framework, build command and output directory are
detected automatically.
