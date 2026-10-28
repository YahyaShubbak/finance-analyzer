import { useCallback, useRef, useState } from "react";
import { useI18n } from "../../i18n/useI18n";
import clsx from "clsx";

export function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const { t } = useI18n();
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    (fileList: FileList | null) => {
      if (!fileList) return;
      onFiles(Array.from(fileList));
    },
    [onFiles]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        handleFiles(e.dataTransfer.files);
      }}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      aria-label={`${t("imports.drop")} — ${t("imports.dropHint")}`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
      className={clsx(
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
        "border-2 border-dashed rounded-lg px-6 py-14 text-center cursor-pointer transition-colors",
        isDragging ? "border-accent bg-accent-soft" : "border-border-strong hover:border-accent hover:bg-surface-sunken"
      )}
    >
      <div className="text-sm font-medium text-ink">{t("imports.drop")}</div>
      <div className="text-xs text-ink-muted mt-1">{t("imports.dropHint")}</div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".csv,.xlsx,.pdf"
        className="hidden"
        onChange={(e) => {
          handleFiles(e.target.files);
          // Allow choosing the same file again (e.g. after removing its card).
          e.target.value = "";
        }}
      />
    </div>
  );
}
