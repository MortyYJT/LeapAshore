"use client";

import { fetchMaterials } from "../api";
import { toMaterials } from "../materials-source";
import type { Material } from "../types";
import { useResource } from "./useResource";

export async function loadMaterials(): Promise<Material[]> {
  return toMaterials(await fetchMaterials());
}

export function useMaterials() {
  return useResource(loadMaterials);
}
