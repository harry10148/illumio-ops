// Pages add themselves to the left navigation; a page that is not built does not
// appear (no placeholders).
import type { ComponentType } from "react";

export type NavSection = "system";

export interface NavItem {
  section: NavSection;
  path: string;
  labelKey: string;
  order: number;
  component: ComponentType;
}

const items: NavItem[] = [];

export function registerNav(item: NavItem): void {
  items.push(item);
}

export function navItems(section: NavSection): NavItem[] {
  return items.filter((i) => i.section === section).sort((a, b) => a.order - b.order);
}

export function allNavItems(): NavItem[] {
  return [...items];
}
