import { NextResponse, type NextRequest } from "next/server";

import { ONBOARDED_COOKIE } from "./lib/prototype-handoff";

/**
 * A visitor who has finished the onboarding goes straight to the prototype instead of seeing the
 * questionnaire again. Decided here, before the page renders, so there is no flash of the first
 * question on the way.
 */
export function proxy(request: NextRequest) {
  if (request.cookies.get(ONBOARDED_COOKIE)?.value === "1") {
    return NextResponse.redirect(new URL("/prototype", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: "/",
};
