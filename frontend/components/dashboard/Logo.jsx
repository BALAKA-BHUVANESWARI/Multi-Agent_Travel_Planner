// The ExecuTrip mark: a way (dotted route from a starting point) that ends at a wish (the star).
export default function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7.500 19.500H15a3.250 3.250 0 0 0 0-6.500H9a3.250 3.250 0 0 1 0-6.500h1.500" fill="none"
        stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeDasharray="0.1 3.4" />
      <circle cx="4.5" cy="19.5" r="2.2" fill="#fff" />
      <path d="M17.500 1.500l1.500 3.900 3.900 1.500-3.900 1.500-1.500 3.900-1.500-3.900-3.900-1.500 3.900-1.500z" fill="#ffd54a" />
    </svg>
  );
}
