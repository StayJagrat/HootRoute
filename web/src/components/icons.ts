// Inline SVG strings shared by DOM map markers and React components.
const s = (body: string, vb = '0 0 24 24') => `<svg viewBox="${vb}" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${body}</svg>`;

export const ICONS = {
  cafe: s('<path d="M5 9h11v5a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5V9Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M16 11h1.5a2.5 2.5 0 0 1 0 5H16" stroke="currentColor" stroke-width="2"/><path d="M8 3.5c0 1 1 1 1 2M11.5 3.5c0 1 1 1 1 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'),
  market: s('<path d="M3 4h2.5l2 11h10l2-8H7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="9.5" cy="19" r="1.6" fill="currentColor"/><circle cx="16.5" cy="19" r="1.6" fill="currentColor"/>'),
  pharmacy: s('<rect x="4" y="4" width="16" height="16" rx="4" stroke="currentColor" stroke-width="2"/><path d="M12 8v8M8 12h8" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>'),
  hotel: s('<path d="M3 18V6M3 14h18v4M21 14v-2a3 3 0 0 0-3-3h-7v5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="7" cy="11" r="2" stroke="currentColor" stroke-width="2"/>'),
  star: s('<path d="m12 3 2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7L12 3Z" fill="currentColor"/>'),
  train: s('<rect x="5" y="3" width="14" height="14" rx="4" stroke="currentColor" stroke-width="2"/><path d="M5 11h14M8.5 21l2-3.5M15.5 21l-2-3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="9" cy="14" r="1" fill="currentColor"/><circle cx="15" cy="14" r="1" fill="currentColor"/>'),
  home: s('<path d="M4 11 12 4l8 7v9H4v-9Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M10 20v-5h4v5" stroke="currentColor" stroke-width="2"/>'),
  turnLeft: s('<path d="M17 20V12a4 4 0 0 0-4-4H6" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M9.5 4.5 6 8l3.5 3.5" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'),
  turnRight: s('<path d="M7 20V12a4 4 0 0 1 4-4h7" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M14.5 4.5 18 8l-3.5 3.5" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'),
  straight: s('<path d="M12 20V5M6.5 10.5 12 5l5.5 5.5" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'),
  check: s('<path d="m5 12.5 4.5 4.5L19 7.5" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>'),
  moon: s('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z" fill="currentColor"/>'),
  phone: s('<path d="M5 3.5h3.2l1.6 4.3-2.1 1.5a11 11 0 0 0 7 7l1.5-2.1 4.3 1.6V19a2 2 0 0 1-2 2A16.5 16.5 0 0 1 3 5.5a2 2 0 0 1 2-2Z" fill="currentColor"/>'),
  phoneOff: s('<path d="M5 3.5h3.2l1.6 4.3-2.1 1.5a11 11 0 0 0 7 7l1.5-2.1 4.3 1.6V19a2 2 0 0 1-2 2A16.5 16.5 0 0 1 3 5.5a2 2 0 0 1 2-2Z" stroke="currentColor" stroke-width="1.8"/><path d="M3 3l18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'),
  chevronDown: s('<path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'),
  play: s('<path d="M7 4.5v15l12-7.5-12-7.5Z" fill="currentColor"/>'),
  pause: s('<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/>'),
  mic: s('<rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" stroke-width="2"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'),
  volumeOff: s('<path d="M4 9h4l5-4v14l-5-4H4V9Z" fill="currentColor"/><path d="m16 9 5 6M21 9l-5 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'),
  volume: s('<path d="M4 9h4l5-4v14l-5-4H4V9Z" fill="currentColor"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'),
  back: s('<path d="M15 5 8 12l7 7" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'),
  ring: s('<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-opacity="0.35" stroke-width="3"/><path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'),
};

export type IconName = keyof typeof ICONS;
