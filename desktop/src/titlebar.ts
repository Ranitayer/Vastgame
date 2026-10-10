export function titlebarDrag(node: HTMLElement, options: { start: () => Promise<void>; onerror: () => void }) {
  let origin: { x: number; y: number } | undefined;
  let dragged = false;
  let releaseTimer: ReturnType<typeof setTimeout> | undefined;
  const down = (event: MouseEvent) => {
    clearTimeout(releaseTimer);
    origin = undefined; dragged = false;
    // Keep native controls and the existing native drag region independent.
    if (event.button !== 0 || (event.target as Element).closest('.window-controls button, [data-tauri-drag-region]')) return;
    // Native movement can consume mouseup; do not leave the webview button pressed.
    event.preventDefault();
    (event.target as Element).closest<HTMLElement>('button')?.focus({ preventScroll: true });
    origin = { x: event.clientX, y: event.clientY };
  };
  const move = (event: MouseEvent) => {
    if (!(event.buttons & 1)) { origin = undefined; dragged = false; return; }
    if (!origin) return;
    if (Math.hypot(event.clientX - origin.x, event.clientY - origin.y) < 4) return;
    origin = undefined; dragged = true;
    event.preventDefault();
    void options.start().catch(() => { dragged = false; options.onerror(); });
  };
  const release = () => {
    origin = undefined;
    // Block only this release's click, never the next independent click.
    clearTimeout(releaseTimer);
    releaseTimer = setTimeout(() => dragged = false, 0);
  };
  const cancel = () => { clearTimeout(releaseTimer); origin = undefined; dragged = false; };
  const click = (event: MouseEvent) => {
    // Moving a tab must not select it or activate Save/Reset on release.
    if (dragged && event.detail > 0) { event.preventDefault(); event.stopImmediatePropagation(); }
    dragged = false;
  };
  node.addEventListener('mousedown', down, true);
  node.addEventListener('click', click, true);
  document.addEventListener('mousemove', move, true);
  document.addEventListener('mouseup', release, true);
  document.addEventListener('pointercancel', cancel, true);
  return { destroy() {
    clearTimeout(releaseTimer);
    node.removeEventListener('mousedown', down, true);
    node.removeEventListener('click', click, true);
    document.removeEventListener('mousemove', move, true);
    document.removeEventListener('mouseup', release, true);
    document.removeEventListener('pointercancel', cancel, true);
  } };
}
