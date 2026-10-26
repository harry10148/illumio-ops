// Pages add themselves to the left navigation; a page that is not built does not
// appear (no placeholders).
import type { ComponentType } from "react";

export type NavSection = "main" | "system";

export interface NavItem {
  section: NavSection;
  path: string;
  labelKey: string;
  order: number;
  component: ComponentType;
  /** A page reached from another page (a detail, an editor): routed, not listed in the navigation. */
  hidden?: boolean;
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
