import Icon from "./Icon.jsx";
import Logo from "./Logo.jsx";

const ITEMS = [
  ["home", "Home", "home"],
  ["trips", "My Trips", "trips"],
  ["explore", "Explore Destinations", "globe"],
  ["insights", "Travel Insights", "chart"],
  ["profile", "Profile", "user"],
  ["help", "Emergency Help", "help"],
];

export default function Sidebar({ active, onSelect }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="logo"><Logo size={30} /></span>
        <span><b>ExecuTrip:</b><small>Wish-to-Way</small></span>
      </div>
      <nav aria-label="Main">
        {ITEMS.map(([key, label, icon]) => (
          <button type="button" key={key} data-nav={key} aria-current={active === key ? "page" : undefined}
            onClick={() => onSelect(key)}>
            <Icon name={icon} />{label}
          </button>
        ))}
      </nav>
      <div className="powered">
        <svg width="64" height="58" viewBox="0 0 64 58" aria-hidden="true">
          <path d="M32 4v8" stroke="#6a5cff" strokeWidth="3" /><circle cx="32" cy="4" r="3" fill="#6a5cff" />
          <rect x="10" y="12" width="44" height="32" rx="14" fill="#fff" stroke="#6a5cff" strokeWidth="3" />
          <rect x="18" y="20" width="28" height="15" rx="7" fill="#1c2a55" />
          <circle cx="26" cy="27.5" r="3" fill="#6fe3ff" /><circle cx="38" cy="27.5" r="3" fill="#6fe3ff" />
          <path d="M20 54c2-7 22-7 24 0z" fill="#6a5cff" />
        </svg>
        <b>Powered by<br />Multi-Agent AI</b>
        <small>Plan · Research · Check · Personalise</small>
      </div>
    </aside>
  );
}
