import "server-only";

// Reads the Next server makes itself: the return-visit redirect and the server-rendered library pages.
// The browser reaches the API through Caddy (production) or the dev rewrite; the server cannot, so it
// calls the API directly at API_ORIGIN (design D2): 127.0.0.1:8000 locally, http://api:8000 in the
// production compose file.

import { fetchProgramPage, fetchUniversities, type ProgramQuery } from "./api";

export const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

export function serverProgramPage(query: ProgramQuery) {
  return fetchProgramPage(query, API_ORIGIN);
}

export function serverUniversities() {
  return fetchUniversities(API_ORIGIN);
}
