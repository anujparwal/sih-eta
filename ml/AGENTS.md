# Machine learning

Follow the root guide. Phase 5 uses XGBoost JSON artifacts and exact native
TreeSHAP contributions (no pickle). Keep the independent current-delay
carryover baseline. Import backend feature calculations; never duplicate them.

Training requires explicit authorization for a local training run. The user
authorized the initial Phase 5 local synthetic training/evaluation. Routine
CI loads and tests the reviewed artifact; it never retrains it.

Split complete journeys chronologically, purge boundary crossings, select
parameters only on validation, and evaluate the test period once. Evaluate
serving fallbacks and clipping too. Never use unversioned historical averages
as model inputs. Keep missing observations null/NaN, not fabricated zeros.

Store reviewed exports in models/ and evidence in results/. Generated telemetry
belongs in ignored data/. Document checksums, dependency versions, data
provenance, time boundaries and limitations. Synthetic evaluation cannot prove
real railway accuracy. Run the full backend suite and Ruff, including this
folder, before publishing. Do not broaden the next-station model to downstream
stations without training and evaluating that different target.
