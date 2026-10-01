import { NextRequest, NextResponse } from "next/server";

// A read-only, fixed-upstream proxy. No credentials or internal hostnames reach the browser.
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const path = (await params).path.join("/");
  if (
    !/^(network|trains|live\/trains\/[0-9]{5}|control\/fleet-status|trains\/\d{5}\/(eta|history)|stations\/[A-Z0-9]{1,10}\/arrivals)$/.test(
      path,
    )
  ) {
    return NextResponse.json({ detail: "Unknown resource" }, { status: 404 });
  }
  const base =
    process.env.API_INTERNAL_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://127.0.0.1:8000";
  try {
    const url = new URL(`${base.replace(/\/$/, "")}/${path}`);
    for (const key of [
      "active_only",
      "include_stale",
      "journey_id",
      "after",
      "limit",
      "date",
    ]) {
      const value = request.nextUrl.searchParams.get(key);
      if (value !== null) url.searchParams.set(key, value);
    }
    const response = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(path.startsWith("live/") ? 20000 : 8000),
    });
    if (!response.ok && path.startsWith("live/")) {
      const body = await response.json();
      return NextResponse.json(
        { detail: typeof body.detail === "string" ? body.detail : "Enter a valid train number and journey start date." },
        { status: response.status, headers: { "Cache-Control": "no-store" } },
      );
    }
    if (!response.ok)
      return NextResponse.json(
        {
          detail:
            response.status === 404
              ? "Not found in this demo network"
              : "Train data is temporarily unavailable",
        },
        { status: response.status === 404 ? 404 : 503 },
      );
    return NextResponse.json(await response.json(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { detail: "Train data is temporarily unavailable" },
      { status: 503 },
    );
  }
}
