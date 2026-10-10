export async function copyText(text: string): Promise<void> {
  try { await navigator.clipboard.writeText(text); }
  catch {
    // Older Linux webviews lack the async clipboard API.
    const previous = document.activeElement as HTMLElement | null;
    const field = document.createElement('textarea');
    field.value = text;
    field.style.cssText = 'position:fixed;left:-9999px;top:0';
    document.body.append(field);
    try {
      field.focus({ preventScroll: true }); field.select();
      if (!document.execCommand('copy')) throw new Error('Could not copy. Select the text and copy manually.');
    } finally { field.remove(); previous?.focus({ preventScroll: true }); }
  }
}
