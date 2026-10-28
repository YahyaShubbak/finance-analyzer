import { getFormatLocale } from "./format";

const regionNames = new Map<string, Intl.DisplayNames | null>();

/** "DE" -> "Deutschland" / "Germany", in the chosen language; the code itself if unknown. */
export function countryName(code: string): string {
  const locale = getFormatLocale();
  if (!regionNames.has(locale)) {
    try {
      regionNames.set(locale, new Intl.DisplayNames([locale], { type: "region" }));
    } catch {
      regionNames.set(locale, null);
    }
  }
  try {
    return regionNames.get(locale)?.of(code.toUpperCase()) ?? code;
  } catch {
    return code; // not a region code Intl knows
  }
}

/** "Palma, Spanien", "Spanien", or null without a known place (online purchases aside). */
export function placeLabel(place: { country: string | null; city: string | null }): string | null {
  if (!place.country) return null;
  return place.city ? `${place.city}, ${countryName(place.country)}` : countryName(place.country);
}
