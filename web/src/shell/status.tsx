// The frame's live facts (GET /api/shell/status): pages read the mode from here to explain what basic mode leaves
// out instead of drawing an empty table.
import { createContext, useContext, useEffect, useState } from "react";

import { call } from "../api/client";
import type { ShellStatus } from "../api/generated";

const REFRESH_MS = 60_000;

export const ShellStatusContext = createContext<ShellStatus | null>(null);

export function useShellStatus(): ShellStatus | null {
  return useContext(ShellStatusContext);
}

/** True only when the status says basic mode; unknown (not loaded yet) is not basic. */
export function useBasicMode(): boolean {
  return useShellStatus()?.mode === "basic";
}

export function useShellStatusPoll(): ShellStatus | null {
  const [status, setStatus] = useState<ShellStatus | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => {
      void call("shell.status").then((env) => {
        if (live && env.ok && env.data) setStatus(env.data);
      });
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);
  return status;
}
