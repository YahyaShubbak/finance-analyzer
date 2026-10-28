import { apiDelete, apiGet, apiPatch, apiPost } from "./client";
import type { CategoryInfo } from "../types";

export function listCategories() {
  return apiGet<CategoryInfo[]>("/api/categories");
}

export function createCategory(name: string) {
  return apiPost<CategoryInfo>("/api/categories", { name });
}

export function renameCategory(id: number, name: string) {
  return apiPatch<CategoryInfo>(`/api/categories/${id}`, { name });
}

/** Without a replacement its transactions become "Other …" and go to review. */
export function deleteCategory(id: number, replacement: string | null) {
  const query = replacement ? `?replacement=${encodeURIComponent(replacement)}` : "";
  return apiDelete<{ transactions_moved: number }>(`/api/categories/${id}${query}`);
}
