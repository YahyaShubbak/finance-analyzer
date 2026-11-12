import { ImportFileCard } from "./ImportFileCard";
import { removeFile, saveSnapshot, showReview, useImportQueue, useReviewKey } from "../../state/importQueue";

/** The files waiting to be imported, each with what it has reached — kept
 * outside the page (state/importQueue), so they survive a visit to another one. */
export function ImportFileCards({ autoImport }: { autoImport: boolean }) {
  const queue = useImportQueue();
  const reviewKey = useReviewKey();
  if (queue.length === 0) return null;
  return (
    <div className="space-y-3">
      {queue.map((qf) => (
        <ImportFileCard
          key={qf.key}
          file={qf.file}
          autoImport={autoImport}
          snapshot={qf.snapshot}
          onSnapshot={(patch) => saveSnapshot(qf.key, patch)}
          onRemove={() => removeFile(qf.key)}
          reviewOpen={reviewKey === qf.key}
          reviewElsewhere={reviewKey !== null && reviewKey !== qf.key}
          onReview={(open) => showReview(qf.key, open)}
        />
      ))}
    </div>
  );
}
