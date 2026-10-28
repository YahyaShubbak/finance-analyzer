import { apiGet, apiPatch } from "./client";
import type { PointsProgram } from "../types";

export function listPoints() {
  return apiGet<PointsProgram[]>("/api/points");
}

export function updatePointsProgram(id: number, changes: { name?: string; value_per_100?: number }) {
  return apiPatch<PointsProgram>(`/api/points/programs/${id}`, changes);
}
