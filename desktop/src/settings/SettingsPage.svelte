<script lang="ts">
  import { tick } from 'svelte';
  import SensitiveSettings from './SensitiveSettings.svelte';
  import Button from '../components/Button.svelte';
  import Dropdown from '../components/Dropdown.svelte';
  import NumberField from '../components/NumberField.svelte';
  import Range from '../components/Range.svelte';
  import Toggle from '../components/Toggle.svelte';
  import Popover from '../components/Popover.svelte';
  import { hosts } from '../hosts/catalog.svelte';
  import { gpuName } from '../hosts/types';
  import { preferences, ensurePreferences, savePreferences, resetPreferences, type HostPreferences, type Preferences } from './preferences.svelte';
  let { active, reset = $bindable<(() => Promise<void>) | undefined>(), save = $bindable<(() => Promise<void>) | undefined>(), saved = $bindable(false) }: { active: boolean; reset?: () => Promise<void>; save?: () => Promise<void>; saved?: boolean } = $props();
  let initialized = $state(false);
  let codec = $state(''), fps = $state(''), resolution = $state(''), bitrate = $state(0);
  let decoder = $state(''), format = $state(''), display = $state('');
  let pacing = $state(true), vsync = $state(false), audio = $state('');
  let host = $state<HostPreferences>({ country: '', preferred_gpu: '', spending_limit_usd: 0, verified_only: false, min_download_mbps: 0, min_upload_mbps: 0, min_vram_gb: 0, min_ram_gb: 0 });
  let saveError = $state('');
  let errorAnchor = $state<HTMLElement>();
  let pageElement = $state<HTMLDivElement>();
  let previous = '';
  const payload = $derived<Preferences>({ stream: { video_codec: codec || 'auto', fps: fps ? Number(fps) : 'native', resolution: resolution || 'native', bitrate_mbps: bitrate || null, video_decoder: decoder || 'auto', display_mode: display || 'fullscreen', moonlight_options: { 'frame-pacing': pacing, vsync, yuv444: format === '444', 'audio-config': audio || 'stereo' } }, hosts: host });
  const fingerprint = $derived(JSON.stringify(payload));
  $effect(() => { if (initialized && fingerprint !== previous) { saved = false; previous = fingerprint; } });
  $effect(() => { save = initialized ? saveAll : undefined; reset = resetAll; });
  const rates = $derived([...new Set(['30', '60', '90', '120', '144', '165', '240', ...(fps ? [fps] : [])])].sort((a, b) => Number(a) - Number(b)).map(value => ({ value, label: `${value} FPS` })));
  const sizes = $derived([...new Set(['1280x720', '1920x1080', '1920x1200', '2560x1440', '2560x1600', '3440x1440', '3840x2160', '5120x1440', ...(resolution ? [resolution] : [])])].map(value => ({ value, label: value.replace('x', ' × ') })));
  const gpus = $derived([...new Set([...(hosts.catalog?.offers.map(gpuName) ?? []), ...(host.preferred_gpu ? [host.preferred_gpu] : [])])].sort());
  $effect(() => { if (active) void ensurePreferences(); });
  $effect(() => {
    if (!preferences.data || initialized) return;
    const saved = preferences.data;
    codec = saved.stream.video_codec === 'auto' ? '' : saved.stream.video_codec;
    fps = saved.stream.fps === 'native' ? '' : String(saved.stream.fps);
    resolution = saved.stream.resolution === 'native' ? '' : saved.stream.resolution;
    bitrate = saved.stream.bitrate_mbps ?? 0;
    decoder = saved.stream.video_decoder === 'auto' ? '' : saved.stream.video_decoder || '';
    display = saved.stream.display_mode === 'fullscreen' ? '' : saved.stream.display_mode || '';
    format = saved.stream.moonlight_options?.yuv444 === true ? '444' : '';
    pacing = saved.stream.moonlight_options?.['frame-pacing'] !== false;
    vsync = saved.stream.moonlight_options?.vsync === true;
    audio = saved.stream.moonlight_options?.['audio-config'] === 'stereo' ? '' : String(saved.stream.moonlight_options?.['audio-config'] || '');
    host = { ...saved.hosts }; initialized = true;
  });
  async function resetAll() {
    saveError = '';
    try { await resetPreferences(); initialized = false; await tick(); saved = true; }
    catch (error) { saved = false; saveError = String(error); }
  }
  async function saveAll() {
    saveError = '';
    const submitted = fingerprint;
    try {
      await savePreferences($state.snapshot(payload));
      saved = fingerprint === submitted;
    } catch (error) { saved = false; saveError = String(error); }
  }

</script>
{#if active}
<div class="settings-page" bind:this={pageElement}>
  {#if !initialized}
    <p class="message" role={preferences.error ? 'alert' : 'status'}>{preferences.error || 'Loading settings…'}</p>
    {#if preferences.error}<Button onclick={() => void ensurePreferences()}>Retry</Button>{/if}
  {:else}
  <div class="settings-grid">
    <div class="settings-column">
    <section class="settings-box streaming" aria-labelledby="streaming-heading">
      <header bind:this={errorAnchor}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="13" rx="2"/><path d="M12 16v5M7 21h10"/></svg><h2 id="streaming-heading">Streaming</h2><p title="Choose your Moonlight stream quality.">Choose your Moonlight stream quality.</p></header>
      <div class="row"><span>Preferred codec</span><Dropdown bind:value={codec} options={['H.264', 'HEVC', 'AV1']} label="Preferred stream codec" placeholder="Auto (recommended)"/></div>
      <div class="row"><span>Decoder</span><Dropdown bind:value={decoder} options={[{ value: 'hardware', label: 'Hardware' }, { value: 'software', label: 'Software' }]} label="Stream decoder" placeholder="Auto (recommended)"/></div>
      <div class="row"><span>Color format</span><Dropdown bind:value={format} options={[{ value: '444', label: 'YUV 4:4:4' }]} label="Stream color format" placeholder="YUV 4:2:0"/></div>
      <div class="row"><span>Display mode</span><Dropdown bind:value={display} options={[{ value: 'windowed', label: 'Windowed' }, { value: 'borderless', label: 'Borderless' }]} label="Stream display mode" placeholder="Fullscreen"/></div>
      <div class="row"><span>Frame rate</span><Dropdown bind:value={fps} options={rates} label="Target frame rate" placeholder="Native refresh rate"/></div>
      <div class="row"><span>Resolution</span><Dropdown bind:value={resolution} options={sizes} label="Stream resolution" placeholder="Native display"/></div>
      <div class="row"><span>Frame pacing</span><Toggle bind:checked={pacing} label="Frame pacing" disabled={preferences.saving}/></div>
      <div class="row"><span>VSync</span><Toggle bind:checked={vsync} label="Vertical sync" disabled={preferences.saving}/></div>
      <div class="row"><span>Audio configuration</span><Dropdown bind:value={audio} options={[{ value: '5.1-surround', label: '5.1 surround' }, { value: '7.1-surround', label: '7.1 surround' }]} label="Stream audio configuration" placeholder="Stereo"/></div>
      <div class="row"><span>Bitrate</span><Range bind:value={bitrate} max={500} label="Stream bitrate (Auto uses the Moonlight default)" text={bitrate ? `${bitrate} Mbps` : 'Auto'}/></div>
    </section>
    <SensitiveSettings/>
    </div>
    <section class="settings-box" aria-labelledby="hosts-heading">
      <header><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18M5 6h14M5 18h14"/></svg><h2 id="hosts-heading">Hosts &amp; Region</h2><p title="Filter hosts and tailor Best value to you.">Filter hosts and tailor Best value to you.</p></header>
      <div class="row"><span>Your country</span><Dropdown bind:value={host.country} options={preferences.countries} label="Your country" placeholder="No preference"/></div>
      <div class="row"><span>Preferred GPU</span><Dropdown bind:value={host.preferred_gpu} options={gpus} label="Preferred GPU" placeholder="Any GPU"/></div>
      <div class="row"><span>Session spending limit</span><NumberField bind:value={host.spending_limit_usd} label="Session spending limit" max={100000} step={0.1} unit="USD" disabled={preferences.saving}/></div>
      <div class="row"><span>Verified hosts only</span><Toggle bind:checked={host.verified_only} label="Show only verified hosts" disabled={preferences.saving}/></div>
      <div class="row"><span>Minimum download</span><NumberField bind:value={host.min_download_mbps} label="Minimum host download speed" max={100000} step={10} unit="Mbps" disabled={preferences.saving}/></div>
      <div class="row"><span>Minimum upload</span><NumberField bind:value={host.min_upload_mbps} label="Minimum host upload speed" max={100000} step={10} unit="Mbps" disabled={preferences.saving}/></div>
      <div class="row"><span>Minimum VRAM</span><NumberField bind:value={host.min_vram_gb} label="Minimum host VRAM" max={1024} unit="GB" disabled={preferences.saving}/></div>
      <div class="row"><span>Minimum RAM</span><NumberField bind:value={host.min_ram_gb} label="Minimum host RAM" max={65536} unit="GB" disabled={preferences.saving}/></div>
    </section>
  </div>
  {/if}
</div>
<Popover open={!!saveError} anchor={errorAnchor ?? pageElement} persistent label="Settings error" onclose={() => saveError = ''}><p role="alert">{saveError}</p></Popover>
{/if}
<style>
  .settings-page { height: 100%; min-width: 0; container-type: size; }
  .settings-grid {
    --settings-gap: min(calc(var(--page-margin) / 3), clamp(2px, calc((100cqh - 468px) / 80 + 2px), 8px));
    --settings-heading-size: clamp(20px, calc((100cqh - 468px) / 15 + 20px), 26px);
    --sensitive-action-padding: clamp(0px, calc((100cqh - 468px) / 12), 12px);
    /* Reserve both headers, card insets, two 32px actions and their gaps;
       the remaining height fits Streaming's ten rows without page scrolling. */
    --button-size: clamp(28px, calc((100cqh - 5 * var(--page-margin) - 2 * var(--settings-heading-size) - 64px - 4 * var(--sensitive-action-padding) - 12 * var(--settings-gap)) / 10), 40px);
    height: 100%; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: var(--page-margin);
  }
  .settings-column { height: 100%; display: flex; flex-direction: column; gap: var(--page-margin); min-width: 0; min-height: 0; }
  .streaming { flex: 1; justify-content: space-between; min-height: 0; }
  .settings-column :global(.settings-box) { flex-shrink: 0; }
  .settings-grid :global(.settings-box) { display: flex; flex-direction: column; gap: var(--settings-gap); padding: var(--page-margin); background: var(--surface-hover); border-radius: 24px; min-width: 0; container-type: inline-size; }
  .settings-grid :global(.settings-box > header) { display: flex; align-items: center; gap: 8px; min-width: 0; height: var(--settings-heading-size); }
  .settings-grid :global(.settings-box > header svg) { width: var(--settings-heading-size); height: var(--settings-heading-size); flex-shrink: 0; }
  .settings-grid :global(.settings-box > header h2) { margin: 0; font-size: clamp(14px, calc((100cqh - 468px) / 40 + 14px), 16px); line-height: 1.2; flex-shrink: 0; }
  header p, .message { margin: 0; color: var(--text-muted); font-size: 12px; line-height: 1.5; }
  .row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr); align-items: center; gap: var(--page-margin); min-height: var(--button-size); font-size: 12px; line-height: 1.15; }
  .row :global(.dropdown) { width: 100%; }
  .row :global(.range) { grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 8px; }
  header p { margin-left: auto; text-align: right; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  @container (max-width: 380px) {
    .row { grid-template-columns: minmax(0, 1fr) minmax(0, 1.6fr); gap: 8px; }
    .row :global(.number-field) { padding-left: 8px; gap: 4px; }
    .row :global(.face) { padding-inline: 8px; }
    .row :global(.icon .face) { padding: 0; }
  }
</style>
