export const tabs = [
  { id: 'home', label: 'Home', icon: 'm3 10 9-7 9 7v10H3z M9 20v-7h6v7' },
  { id: 'library', label: 'Library', icon: 'M4 4h4v16H4z M11 4h4v16h-4z M18 4l3 15' },
  { id: 'hosts', label: 'Hosts', icon: 'M4 4h16v6H4z M4 14h16v6H4z M7 7h.01 M7 17h.01' },
  { id: 'sessions', label: 'Sessions', icon: 'M12 3a9 9 0 1 0 9 9 M12 7v5l3 2 M17 3v5h5' },
  { id: 'billing', label: 'Billing', icon: 'M3 5h18v14H3z M3 9h18 M6 15h4' },
  { id: 'settings', label: 'Settings', icon: 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6' },
] as const;

export type TabId = typeof tabs[number]['id'];
