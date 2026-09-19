const views = [
  { name: "Passenger", detail: "Train search, journey progress, and arrival estimates." },
  { name: "Station board", detail: "Upcoming arrivals in a clear station display." },
  { name: "Control room", detail: "Fleet delays, active events, and journey details." },
];

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16 sm:px-10">
      <p className="text-sm font-semibold tracking-widest text-teal-700">SIH 2026 · PHASE 4</p>
      <h1 className="mt-5 max-w-3xl text-4xl font-semibold tracking-tight text-slate-950 sm:text-6xl">
        Dynamic Train ETA
      </h1>
      <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">
        A foundation for forecasting coaching train arrivals on Indian routes.
        The backend now provides baseline arrival estimates, journey history, and live updates
        for six simulated trains. The passenger, station, and control views below will follow.
      </p>
      <section aria-labelledby="views-heading" className="mt-12">
        <h2 id="views-heading" className="text-sm font-semibold text-slate-600">Planned views</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {views.map((view) => (
            <article key={view.name} className="rounded-2xl border border-slate-200 bg-white p-6">
              <h3 className="font-semibold text-slate-950">{view.name}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-600">{view.detail}</p>
              <p className="mt-5 text-xs font-medium text-slate-500">Planned · Phase 6</p>
            </article>
          ))}
        </div>
      </section>
      <p className="mt-10 text-sm leading-6 text-slate-500">
        MVP target: six simulated coaching trains, one shared API, and explainable ETA predictions.
        No live railway data is connected.
      </p>
    </main>
  );
}
