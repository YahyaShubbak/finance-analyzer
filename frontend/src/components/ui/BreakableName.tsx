import { Fragment } from "react";

/** A file name without spaces ("Finanzreport_Nr._06_per_01.07.2025.pdf"),
 * allowed to wrap after "_", "-" and "." instead of overflowing its column. */
export function BreakableName({ name }: { name: string }) {
  const parts = name.split(/(?<=[_\-.])/);
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 && <wbr />}
        </Fragment>
      ))}
    </>
  );
}
