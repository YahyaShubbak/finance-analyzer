import { apiPost } from "./client";
import type { TransferDetectionResult } from "../types";

export function rerunTransferDetection() {
  return apiPost<TransferDetectionResult>("/api/transfers/rerun-detection");
}
