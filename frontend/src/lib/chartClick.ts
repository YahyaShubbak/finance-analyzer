/** Which column of the chart a click hit, as the chart library reports it
 * (a number, a number as text — or nothing for a click beside the columns:
 * read as a number, that would be 0, the first month). */
export function clickedIndex(activeIndex: unknown): number | null {
  if (activeIndex === null || activeIndex === undefined || activeIndex === "") return null;
  const index = Number(activeIndex);
  return Number.isInteger(index) && index >= 0 ? index : null;
}
