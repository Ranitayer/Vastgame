export interface Host {
  id: number;
  machine_id: number | null;
  score: number | null;
  gpu_name: string;
  geolocation: string;
  dph_total: number;
  cpu_name: string;
  gpu_ram: number | null;
  cpu_ram: number | null;
  cpu_cores_effective: number | null;
  cpu_ghz: number | null;
  disk_space: number | null;
  inet_down: number | null;
  inet_up: number | null;
}

export interface HostCatalog { offers: Host[]; disk_gb: number; updated: number; }
const numbers = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
export const countryCode = (value: string) => value.replaceAll('_', ' ').match(/(?:,|\s)\s*([A-Z]{2})$/i)?.[1].toUpperCase() ?? '';
export function amount(value: number | null, unit = '', divisor = 1): string {
  return value === null ? 'Not reported' : `${numbers.format(value / divisor)}${unit ? ' ' + unit : ''}`;
}
const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 3 });
export const price = (value: number) => dollars.format(value);
export const gpuName = (host: Host) => host.gpu_name.replaceAll('_', ' ');
export const location = (host: Host) => host.geolocation.replaceAll('_', ' ');
export const hostSummary = (host: Host, download = false, disk = true) => [location(host), gpuName(host), amount(host.gpu_ram, 'GB VRAM', 1024), ...(download ? [amount(host.inet_down, 'Mbps download')] : []), ...(disk ? [amount(host.disk_space, 'GB disk')] : []), `${price(host.dph_total)}/h`].join(' – ');
export const hostSortOptions = ['Highest price', 'Best value'];
export const hostPriceCeiling = (offers: Host[]) => Math.max(0.01, Math.ceil(offers.reduce((max, host) => Math.max(max, host.dph_total), 0) * 100) / 100);
export const sortHosts = (offers: Host[], sort = '') => [...offers].sort((a, b) =>
  (sort === 'Highest price' ? b.dph_total - a.dph_total : sort === 'Best value' ? (b.score ?? -1) - (a.score ?? -1) : a.dph_total - b.dph_total) || a.dph_total - b.dph_total || a.id - b.id);
