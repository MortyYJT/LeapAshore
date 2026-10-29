import { NextResponse, type NextRequest } from "next/server";

import { landingFor } from "./lib/landing";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";
// The anonymous subject (login mode off) and the session (login mode on, openspec account-login).
const COOKIES = ["leapashore_client", "leapashore_session"];

/**
 * A returning applicant whose profile holds the four basics goes straight to the roadmap (spec
 * app-navigation). Decided before the page renders, from the server's profile, with a one-second limit
 * (design D2). Only the two subject cookies are forwarded to the API.
 */
export async function proxy(request: NextRequest) {
  const cookie = COOKIES.map((name) => [name, request.cookies.get(name)?.value] as const)
    .filter(([, value]) => value)
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  if (!cookie) return NextResponse.next();
  const landing = await landingFor(async () => {
    const response = await fetch(`${API_ORIGIN}/api/profile`, {
      headers: { cookie },
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
