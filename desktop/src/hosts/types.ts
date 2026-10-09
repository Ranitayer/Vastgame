export interface Host {
  id: number;
  score: number | null;
  gpu_name: string;
  geolocation: string;
  dph_total: number;
  cpu_name: string;
  disk_name: string;
  gpu_ram: number | null;
  cpu_ram: number | null;
  cpu_cores_effective: number | null;
  cpu_ghz: number | null;
  disk_space: number | null;
  disk_bw: number | null;
  inet_down: number | null;
  inet_up: number | null;
  inet_down_cost: number | null;
  inet_up_cost: number | null;
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
