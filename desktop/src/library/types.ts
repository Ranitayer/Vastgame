export interface Game {
  id: string;
  steam_appid: number | null;
  name: string;
  packaged: boolean;
  required_disk_gb: number | null;
  download_bytes: number | null;
}
export interface LibraryCatalog { games: Game[]; skipped: number; }
export const gameSize = (bytes: number | null) => bytes === null ? 'Not reported' :
  `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(bytes / 1024 ** 3)} GiB`;
