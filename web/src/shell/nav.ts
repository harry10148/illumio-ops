// Pages add themselves to the left navigation; a page that is not built does not
// appear (no placeholders). Sections follow the UI redesign spec §3: the work (main),
// what the product puts out (output), and the settings at the bottom; "system" pages
// are listed in the System page's own sub-navigation.
import type { ComponentType } from "react";

export type NavSection = "main" | "output" | "bottom" | "system";

export interface NavItem {
  section: NavSection;
  path: string;
  labelKey: string;
  order: number;
  component: ComponentType;
  /** A page reached from another page (a detail, an editor): routed, not listed in the navigation. */
  hidden?: boolean;
  /** Needs advanced mode (alert or full collection): in basic mode the item is dimmed and marked, never removed. */
  needs?: "advanced";
  /** A count shown next to the label: the alerts fired since the alerts page was last opened. */
  badge?: "new";
  /** Where the item leads when it is not the page's own path (a section whose first page is elsewhere). */
  to?: string;
}

const items: NavItem[] = [];

export function registerNav(item: NavItem): void {
  items.push(item);
}

export function navItems(section: NavSection): NavItem[] {
  return items.filter((i) => i.section === section && !i.hidden).sort((a, b) => a.order - b.order);
}

export function allNavItems(): NavItem[] {
  return [...items];
}
