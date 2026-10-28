/** One question or explanation of the Help page. A paragraph is a string; a
 * list of strings is shown as a bulleted list. */
export interface HelpTopic {
  id: string;
  title: string;
  body: (string | string[])[];
  /** the page where this is done */
  link?: { to: string; label: string };
}

export interface HelpSection {
  id: string;
  title: string;
  intro?: string;
  topics: HelpTopic[];
}
