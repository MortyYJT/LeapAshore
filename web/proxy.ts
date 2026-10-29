import { NextResponse, type NextRequest } from "next/server";

import { landingFor } from "./lib/landing";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";
const COOKIE = "leapashore_client";

/**
 * A returning applicant with a complete assessment goes straight to the roadmap (spec app-navigation).
 * Decided before the page renders, from the server's profile, with a one-second limit (design D2).
 */
export async function proxy(request: NextRequest) {
  const client = request.cookies.get(COOKIE)?.value;
  if (!client) return NextResponse.next();
  const landing = await landingFor(async () => {
    const response = await fetch(`${API_ORIGIN}/api/profile`, {
      headers: { cookie: `${COOKIE}=${client}` },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(String(response.status));
    return (await response.json()) as Record<string, unknown>;
  });
  return landing ? NextResponse.redirect(new URL(landing, request.url)) : NextResponse.next();
}

export const config = {
  matcher: "/",
};
