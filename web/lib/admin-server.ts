import "server-only";

import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import { API_ORIGIN } from "./server-api";

const SESSION_COOKIE = "leapashore_session";

/**
 * The admin pages are the ordinary 404 to anyone the API does not call an admin (openspec
 * source-verification D6): no session, an applicant's session, anonymous mode (the API answers 403 to
 * every admin request there), or an API that cannot be reached. Only the session cookie is forwarded.
 */
export async function requireAdminPage(): Promise<{ email: string }> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) notFound();
  let response: Response | null = null;
  try {
    response = await fetch(`${API_ORIGIN}/api/admin/me`, {
      headers: { cookie: `${SESSION_COOKIE}=${session}` },
      cache: "no-store",
    });
  } catch {
    response = null;
  }
  if (!response || !response.ok) notFound();
  return (await response.json()) as { email: string };
}
