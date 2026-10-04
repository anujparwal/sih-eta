"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ErrorNotice, ViewHeader } from "./common";
import type { Experiment } from "@/lib/experiment";

const controls = [
  { key: "current_delay_minutes", label: "Current delay (min)", min: 0, max: 180, step: 1 },
  { key: "distance_km", label: "Distance to next station (km)", min: 0.1, max: 500, step: 0.1 },
  { key: "elapsed_minutes", label: "Time since last station (min)", min: 0, max: 600, step: 1 },
] as const;
const initial = { current_delay_minutes: "15", distance_km: "20", elapsed_minutes: "15", event_severity: "0", nearby_trains: "0" };
const featureLabels: Record<string, string> = {
  minutes_since_last_station: "Time since last station", distance_remaining_next_station_km: "Distance remaining",
  current_delay_minutes: "Current delay", historical_day_of_week: "Day of week", historical_hour_of_day: "Time of day",
  active_event_count: "Active events", active_event_severity_sum: "Combined event severity",
  active_event_max_severity: "Highest event severity", congestion_index: "Nearby trains",
};
const signed = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;

export function ExperimentLab() {
  const [inputs, setInputs] = useState(initial);
  const [result, setResult] = useState<Experiment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  function change(next: typeof initial) { setInputs(next); setResult(null); setError(null); }
  async function run(event: FormEvent) {
    event.preventDefault();
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const timeout = setTimeout(() => controller.abort(), 10000);
    setLoading(true); setResult(null); setError(null);
    try {
      const response = await fetch(`/api/demo/scenario?${new URLSearchParams(inputs)}`, { signal: controller.signal, cache: "no-store" });
      if (!response.ok) throw new Error("Experiment unavailable. Check the backend and try again.");
      const data: Experiment = await response.json();
      if (data.source !== "hypothetical_synthetic" || !Number.isFinite(data.scenario?.predicted_delay_minutes)) throw new Error("Invalid experiment response.");
      if (active.current === controller) setResult(data);
    } catch (failure) {
      if (active.current === controller) setError(controller.signal.aborted ? "Experiment timed out. Try again." : failure instanceof Error ? failure.message : "Experiment unavailable.");
    } finally {
      clearTimeout(timeout);
      if (active.current === controller) setLoading(false);
    }
  }
  function download() {
    if (!result) return;
    const blob = new Blob([JSON.stringify({ problem_statement: "SIH26028", exported_at: new Date().toISOString(), ...result }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = "railscope-synthetic-experiment.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const evidence = result?.evidence;
  const explanation = result?.scenario.explanation;
  const scale = result ? Math.max(1, result.baseline_delay_minutes, result.reference.predicted_delay_minutes, result.scenario.predicted_delay_minutes) : 1;
  return <div className="experiment-page">
    <ViewHeader eyebrow="SIH26028 · EXPERIMENT LAB" title="What changes the forecast?"
      subtitle="Explore the next-station model, compare it with a simple baseline, and inspect the evidence behind it." />
    <div className="lab-intro">
      <div><p className="eyebrow">HYPOTHETICAL INPUTS · ACTUAL MODEL INFERENCE</p><h2>A forecast you can question.</h2>
        <p>Change a disruption or nearby-train count. See how the reviewed model responds—and when it refuses to extrapolate.</p></div>
      <div className="lab-intro-note">Synthetic training only<br /><strong>No railway commands. No live ETA.</strong><br />Runs locally without a RailRadar request.</div>
    </div>
    <div className="lab-grid">
      <section className="panel lab-inputs">
        <h2>1. Set the conditions</h2>
        <form onSubmit={run}>
          <fieldset disabled={loading}>
            <legend className="muted small">Hypothetical next-station observation</legend>
            <div className="lab-presets" aria-label="Experiment presets">
              <button type="button" onClick={() => change({ ...initial })}>Quiet section</button>
              <button type="button" onClick={() => change({ ...initial, event_severity: "3" })}>Severe disruption</button>
              <button type="button" onClick={() => change({ ...initial, nearby_trains: "3" })}>Unseen congestion</button>
            </div>
            {controls.map((control) => <label key={control.key}>{control.label}
              <input type="number" required min={control.min} max={control.max} step={control.step} value={inputs[control.key]}
                onChange={(event) => change({ ...inputs, [control.key]: event.target.value })} />
            </label>)}
            <label>Active disruption
              <select value={inputs.event_severity} onChange={(event) => change({ ...inputs, event_severity: event.target.value })}>
                <option value="0">None</option><option value="1">One event · mild</option><option value="2">One event · moderate</option><option value="3">One event · severe</option>
              </select>
            </label>
            <label>Nearby trains
              <select value={inputs.nearby_trains} onChange={(event) => change({ ...inputs, nearby_trains: event.target.value })}>
                {[0, 1, 2, 3, 4, 5].map((value) => <option value={value} key={value}>{value}</option>)}
              </select>
            </label>
            <p className="muted small">Fixed Thursday, 12:00 IST. The reference uses the same delay, distance and elapsed time with no disruption or nearby train. Inputs inside individual training ranges can still form unfamiliar combinations.</p>
            <button className="live-search-button" type="submit">{loading ? "Running experiment…" : "Run experiment"}</button>
          </fieldset>
        </form>
      </section>
      <section className="panel lab-output" aria-label="Experiment result" aria-live="polite">
        <h2>2. Compare the forecast</h2>
        {!result && !error && <div className="lab-empty"><span aria-hidden="true">↗</span><h3>{loading ? "Running the reviewed model…" : "A controlled comparison, on demand."}</h3><p>Choose a preset, then run the experiment. Editing inputs clears the previous result so the numbers always match the conditions shown.</p></div>}
        {error && <ErrorNotice message={error} />}
        {result && <>
          <p className="eyebrow">PREDICTED DELAY AT THE NEXT STATION · MINUTES</p>
          <div className="lab-comparisons">
            {[
              ["Carryover baseline", result.baseline_delay_minutes, "baseline"],
              ["Quiet reference", result.reference.predicted_delay_minutes, "reference"],
              ["Selected scenario", result.scenario.predicted_delay_minutes, "scenario"],
            ].map(([label, value, kind]) => <div className={`lab-comparison ${kind}`} key={label}>
              <div><span>{label}</span><strong>{Number(value).toFixed(2)} min</strong></div>
              <div className="lab-bar-track" aria-hidden="true"><span style={{ width: `${Number(value) / scale * 100}%` }} /></div>
            </div>)}
          </div>
          <div className={`notice ${result.scenario.method === "xgboost" ? "" : "warning"}`} role="status">
            {result.scenario.reason === "model_ready" ? "Selected scenario: XGBoost model prediction." : result.scenario.reason === "outside_training_domain" ? "Baseline fallback: these inputs exceed the model’s training ranges." : "Baseline fallback: the model is unavailable."}
          </div>
          <p className="muted small">Quiet reference: {result.reference.method === "xgboost" ? "XGBoost" : "baseline fallback"}. A lower predicted delay is not proof of a better prediction.</p>
          {result.reference.method === "xgboost" && result.scenario.method === "xgboost" && <p className="lab-delta"><strong>{signed(result.scenario.predicted_delay_minutes - result.reference.predicted_delay_minutes)} min</strong> versus the quiet reference. This is model sensitivity, not a measured causal effect.</p>}
          <p className="muted small">{result.limitation}</p>
          <button className="text-button" type="button" onClick={download}>Download experiment evidence (JSON)</button>
          {explanation && <details className="lab-explanation" open>
            <summary>3. Explain the model output</summary>
            <p className="muted small">These signed contributions add to the prediction. They explain the model, not the cause of a real delay.</p>
            <dl>
              <div><dt>Current delay</dt><dd>{explanation.current_delay_minutes.toFixed(2)} min</dd></div>
              <div><dt>Model starting value</dt><dd>{signed(explanation.base_value_minutes)} min</dd></div>
              {explanation.contributions.map((item) => <div key={item.feature}><dt>{featureLabels[item.feature] || item.feature}</dt><dd>{signed(item.contribution_minutes)} min</dd></div>)}
              <div><dt>Non-negative delay adjustment</dt><dd>{signed(explanation.clipping_adjustment_minutes)} min</dd></div>
              <div className="lab-total"><dt>Predicted delay</dt><dd>{explanation.predicted_delay_minutes.toFixed(2)} min</dd></div>
            </dl>
          </details>}
        </>}
      </section>
    </div>
    <section className="panel lab-evidence" aria-label="Evaluation evidence">
      <p className="eyebrow">MEASURED EVIDENCE · SYNTHETIC JOURNEYS ONLY</p><h2>How well did the model perform?</h2>
      {evidence ? <>
        <div className="lab-score-grid">
          <div><span>Baseline MAE</span><strong>{evidence.baseline_mae_minutes.toFixed(3)} <small>min</small></strong></div>
          <div><span>Model MAE</span><strong>{evidence.model_mae_minutes.toFixed(3)} <small>min</small></strong></div>
          <div><span>Held-out journeys</span><strong>{evidence.test_journeys}</strong></div>
        </div>
        <p>MAE is the average absolute error. RMSE: baseline {evidence.baseline_rmse_minutes.toFixed(3)} min; model {evidence.model_rmse_minutes.toFixed(3)} min.</p>
        <p className="muted small">Chronological journey split: {evidence.training_journeys} training / {evidence.validation_journeys} validation / {evidence.test_journeys} test. The test set contains {evidence.test_rows.toLocaleString("en-IN")} correlated observations, not independent trials. These scores come from the loaded model’s reviewed metadata; this experiment does not rerun evaluation.</p>
        <details><summary>Model identity</summary><p>{evidence.model_version}</p><p className="lab-checksum">SHA-256: {evidence.model_sha256}</p></details>
      </> : <p className="muted">Run an experiment to load the reviewed model’s evaluation evidence. Evidence is unavailable if the model cannot be loaded.</p>}
      <p className="notice warning">Real railway accuracy is not yet measured. A prospective pilot with verified arrivals is the next validation step.</p>
    </section>
    <section className="panel lab-guide">
      <h2>A four-minute demonstration</h2>
      <ol><li><strong>Show the question.</strong> Compare the quiet reference and severe disruption presets. Explain the baseline and model contributions.</li>
        <li><strong>Show the boundary.</strong> Run unseen congestion. Explain why a baseline is returned instead of an unsupported ML estimate.</li>
        <li><strong>Show the evidence.</strong> Present held-out errors, journey splits and the synthetic-data limitation.</li>
        <li><strong>Show integration.</strong> Open a <Link href="/live" className="inline-link">real RailRadar lookup</Link>, then the <Link href="/control" className="inline-link">simulated control room</Link>. State which source each screen uses.</li></ol>
      <p className="muted small">SIH26028 · Dynamic Forecast of Expected Time of Arrival (ETA) for Coaching Trains. No guaranteed accuracy, safety, or operational savings claim.</p>
    </section>
  </div>;
}
