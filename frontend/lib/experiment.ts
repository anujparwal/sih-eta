import type { Explanation } from "./types";
export type ScenarioPrediction = {
  method: "xgboost" | "current_delay_carryover";
  predicted_delay_minutes: number;
  reason: "model_ready" | "outside_training_domain" | "model_unavailable";
  explanation: Explanation | null;
};
export type Experiment = {
  source: "hypothetical_synthetic";
  inputs: Record<string, number>;
  baseline_delay_minutes: number;
  reference: ScenarioPrediction;
  scenario: ScenarioPrediction;
  assumption: string;
  limitation: string;
  evidence: {
    model_version: string;
    baseline_mae_minutes: number;
    model_mae_minutes: number;
    baseline_rmse_minutes: number;
    model_rmse_minutes: number;
    training_journeys: number;
    validation_journeys: number;
    test_journeys: number;
    test_rows: number;
    model_sha256: string;
  } | null;
};
