// Road routes between planned stops, from the OSRM demo server. Its rules: light, non-commercial use and at most
// one request a second, with no guarantee it answers. Only the positions of the planned sights are sent.
const SERVER = "https://router.project-osrm.org/route/v1/driving/";
const GAP_MS = 1100;
const TIMEOUT_MS = 8000;
const known = new Map();
let nextSlot = 0;

async function ask(url) {
  const now = Date.now();
  const wait = Math.max(0, nextSlot - now);
  nextSlot = now + wait + GAP_MS;
  if (wait) await new Promise((done) => setTimeout(done, wait));
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(url, { signal: abort.signal });
    const data = await response.json();
    const route = data.code === "Ok" ? data.routes?.[0] : null;
    if (!route) throw new Error("no road route");
    return {
      line: route.geometry.coordinates.map(([lon, lat]) => [lat, lon]),
      km: route.distance / 1000,
      minutes: route.duration / 60,
    };
  } finally {
    clearTimeout(timer);
  }
}

// stops: [{lat, lon}] in visiting order. A successful answer is remembered; a failure can be tried again.
export function roadRoute(stops) {
  const url = SERVER + stops.map((s) => `${s.lon.toFixed(5)},${s.lat.toFixed(5)}`).join(";") +
    "?overview=full&geometries=geojson";
  if (!known.has(url)) {
    const answer = ask(url);
    answer.catch(() => known.delete(url));
    known.set(url, answer);
  }
  return known.get(url);
}
