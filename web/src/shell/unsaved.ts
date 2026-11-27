import { useEffect } from "react";

const dirtyForms = new Set<symbol>();
let unloadBound = false;

function onBeforeUnload(event: BeforeUnloadEvent): void {
  if (dirtyForms.size === 0) return;
  event.preventDefault();
  event.returnValue = "";
}

export function hasUnsavedChanges(): boolean {
  return dirtyForms.size > 0;
}

export function useUnsavedChanges(dirty: boolean): void {
  useEffect(() => {
    const id = Symbol("dirty-form");
    if (dirty) dirtyForms.add(id);
    if (dirtyForms.size > 0 && !unloadBound) {
      window.addEventListener("beforeunload", onBeforeUnload);
      unloadBound = true;
    }
    return () => {
      dirtyForms.delete(id);
      if (dirtyForms.size === 0 && unloadBound) {
        window.removeEventListener("beforeunload", onBeforeUnload);
        unloadBound = false;
      }
    };
  }, [dirty]);
}
