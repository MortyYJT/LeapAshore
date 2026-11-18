import { NextResponse } from "next/server";
/** The workspace overview is the landing page for every applicant. */
export function proxy() {
  return NextResponse.next();
}
export const config = { matcher: "/" };
