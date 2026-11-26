// Small line icons drawn for this app.
const PATHS = {
  home: "M3 11 12 4l9 7M5 10v10h5v-6h4v6h5V10",
  trips: "M4 6h16v14H4zM4 10h16M8 3v5M16 3v5",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  chart: "M4 20h16M7 20v-6M12 20V6M17 20v-9",
  user: "M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 21c0-4 4-6 8-6s8 2 8 6",
  help: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v10M7 12h10",
  plane: "M21 3 3 10.500l7 2.500 2.500 7zM10 13l11-10",
  pin: "M12 21s-7-6.500-7-11a7 7 0 0 1 14 0c0 4.500-7 11-7 11zM12 8a2.500 2.500 0 1 0 0 5 2.500 2.500 0 0 0 0-5z",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4",
  route: "M6 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM18 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM9 18h6a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6",
  wallet: "M3 7h18v13H3zM3 7l13-4v4M16 13.500h3",
  check: "M5 12.500 10 17l9-10",
  arrow: "M4 12h15M13 6l6 6-6 6",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3 11v1h6v-1a6 6 0 0 0-3-11z",
};

export default function Icon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}
