"use client";

import { fetchApplications } from "../api";
import { toPortfolioItems } from "../programs-source";
import type { PortfolioItem } from "../types";
import { useResource } from "./useResource";

export async function loadPortfolio(): Promise<PortfolioItem[]> {
  return toPortfolioItems(await fetchApplications());
}

/** The saved portfolio. The draft the applicant is editing lives in `portfolio-draft.ts`. */
export function usePortfolio() {
  return useResource(loadPortfolio);
}
