# Public passenger journeys

The home page `/` opens RailRadar train lookup. `/live` remains a compatible
alias. `/demo`, `/station/NDLS`, `/control` and `/lab` are grouped under
**Prototype demos** and keep their synthetic/hypothetical labels. Simulation
train links now lead to `/demo?train=…`.

## Passenger flow

1. Enter a five-digit train number and the date the train left its origin.
   A blank date becomes **today in India** when submitted and is then shown in
   the form. Overnight journeys may require yesterday's origin date.
2. Submit **Look up train**. Opening a page or shared link never requests provider
   data automatically. Changing inputs cancels pending work and clears old results.
3. Choose your destination from the provider route. The card shows full IST dates,
   reported and scheduled arrival, reported platform, source timestamp and notices.
   Missing values remain missing; the timetable is never substituted as a live ETA.
4. **Copy journey link** includes train number, origin date and the exact stop
   sequence/code. Repeated station codes and fractional diversion sequences remain
   distinct. An unavailable or ambiguous saved stop asks for a new selection.
   Clipboard failure offers a selectable URL. Recipients submit to request a report.

Destination selection and copying links reuse the current report and make no
extra provider request. The countdown is a difference from the provider's reported
arrival, **not our model's forecast**. It appears only for a recent, live, running
service and an upcoming confirmed halt with a future arrival report. Cancelled,
skipped, passed, arrived, unknown, missing, stale and past estimates explain why a
current countdown is unavailable. A report ages out after ten minutes even while
the page stays open. Provider cache/fallback warnings suppress countdowns.

Provider reports can change. Displayed platforms must be confirmed at the station;
a reported arrival is not proof of an observed arrival. Check service notices and
the provider timestamp. No estimated confidence interval or measured real-world
accuracy is claimed. See [provider setup](live_data.md).

## Public release boundary

This change implements a passenger-facing prototype, not a public deployment or a
24/7 availability guarantee. Default shared server limits remain 30 upstream
requests/day and 900/month, with five-minute caching. Those defaults protect the
free account but cannot support unrestricted public demand. A public beta needs a
hosting decision, HTTPS, appropriate access/abuse controls and a traffic budget
consistent with the actual provider plan. Do not increase limits merely to remove
errors. Keep the provider key server-side. Synthetic ML validation remains separate
from real passenger reports; no model has been trained on live RailRadar data.

## Verification

`frontend/tests/public-journey.spec.ts` exercises the public entry point, destination
and repeated-stop selection, IST date pinning, exact sharing, clipboard fallback,
in-flight cancellation, report aging and unavailable countdown states on desktop
and mobile. Existing dashboard tests use `/demo`; the real-stack browser smoke
continues to check API, Redis, model and WebSocket behavior there.
