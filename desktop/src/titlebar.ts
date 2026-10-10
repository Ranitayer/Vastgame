export function titlebarDrag(node: HTMLElement, options: { start: () => Promise<void>; onerror: () => void }) {
  let origin: { x: number; y: number; pointer: number } | undefined;
  let dragged = false;
  const down = (event: PointerEvent) => {
    origin = undefined; dragged = false;
    // Keep native controls and the existing native drag region independent.
    if (event.button !== 0 || !event.isPrimary || (event.target as Element).closest('.window-controls, [data-tauri-drag-region]')) return;
    origin = { x: event.clientX, y: event.clientY, pointer: event.pointerId };
  };
  const move = (event: PointerEvent) => {
    if (!origin || event.pointerId !== origin.pointer) return;
    if (!(event.buttons & 1)) { origin = undefined; return; }
    if (Math.hypot(event.clientX - origin.x, event.clientY - origin.y) < 4) return;
    origin = undefined; dragged = true;
    event.preventDefault();
    void options.start().catch(() => { dragged = false; options.onerror(); });
  };
  const release = () => { origin = undefined; };
  const click = (event: MouseEvent) => {
    // Moving a tab must not select it or activate Save/Reset on release.
    if (dragged && event.detail > 0) { event.preventDefault(); event.stopImmediatePropagation(); }
    dragged = false;
  };
  node.addEventListener('pointerdown', down, true);
  node.addEventListener('click', click, true);
  document.addEventListener('pointermove', move, true);
  document.addEventListener('pointerup', release, true);
  document.addEventListener('pointercancel', release, true);
  return { destroy() {
    node.removeEventListener('pointerdown', down, true);
    node.removeEventListener('click', click, true);
    document.removeEventListener('pointermove', move, true);
    document.removeEventListener('pointerup', release, true);
    document.removeEventListener('pointercancel', release, true);
  } };
}
