// Browser tools can add their own focusable overlays beside the application.
export function isWorkspaceTarget(target: EventTarget | null): target is Element {
  return target instanceof Element && target.closest("#root, [data-house-portal]") !== null;
}
