// A coloured message box. kind: "ok" | "warn" | "bad"
export default function Banner({ kind, children }) {
  return <div className={`banner ${kind}`}>{children}</div>;
}
