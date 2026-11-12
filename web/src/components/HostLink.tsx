// Wherever a host or an address is named, it leads to that host's page (purpose-led UI spec §6.3), landing on the
// section the place it was named in is about.
import { Link } from "react-router-dom";

import { HostName } from "./ui";

export type HostSection =
  | "status" | "alerts" | "different" | "usual" | "connections" | "would-block" | "ransomware" | "tamper" | "quarantine";

export function hostPath(hostKey: string, section?: HostSection | null): string {
  return `/hosts?${new URLSearchParams({ key: hostKey }).toString()}${section ? `#${section}` : ""}`;
}

const OPENS = /^(\/orgs\/\d+\/workloads\/|ip:)/;  // what the host page takes (a Kubernetes or container workload is not)

export function HostLink({ hostKey, name, section }: { hostKey: string; name: string; section?: HostSection | null }) {
  if (!OPENS.test(hostKey)) return <HostName name={name} />;
  return (
    <Link to={hostPath(hostKey, section)} data-role="host-link" onClick={(e) => e.stopPropagation()}>
      <HostName name={name} />
    </Link>
  );
}
