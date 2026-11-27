// A place photo: the lead picture of its Wikipedia article, loaded by the visitor's browser. Every photo links to
// its file page, which names the photographer and licence.
const SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/";
const known = new Map();
// very large pictures are served already scaled down, from the "thumb" host
const PICTURE_HOSTS = ["upload.wikimedia.org", "thumb.wikimedia.org"];

export const isPicture = (source) => {
  try {
    const url = new URL(source);
    return url.protocol === "https:" && PICTURE_HOSTS.includes(url.hostname) && !/\.svg(\/|$)/i.test(url.pathname);
  } catch {
    return false;
  }
};

// Wikimedia serves only some thumbnail widths, so `width` must be one of them (500 and 1280 are)
function sized(data, width) {
  const thumb = data.thumbnail?.source;
  const full = data.originalimage;
  if (full && full.width <= width) return full.source;
  return thumb ? thumb.replace(/\/\d+px-/, `/${width}px-`) : full?.source;
}

export function filePage(source) {
  const url = new URL(source);
  const host = url.pathname.startsWith("/wikipedia/commons/") ? "commons.wikimedia.org" : "en.wikipedia.org";
  // a scaled copy's address is .../thumb/a/ab/<file name>/<width>px-<file name>
  const parts = url.pathname.split("/");
  return `https://${host}/wiki/File:${parts.includes("thumb") ? parts[parts.length - 2] : parts[parts.length - 1]}`;
}

async function look(titles, width) {
  for (const title of titles) {
    try {
      const response = await fetch(SUMMARY + encodeURIComponent(title.replace(/ /g, "_")));
      if (!response.ok) continue;
      const data = await response.json();
      const original = data.originalimage?.source;
      if (!original || !isPicture(original)) continue;
      const src = sized(data, width);
      if (!isPicture(src)) continue;
      return { src, page: filePage(original) };
    } catch {
      // offline or blocked: the drawing stays
    }
  }
  return null;
}

export function findPhoto(titles, width = 500) {
  const key = width + "|" + titles.join("|");
  if (!known.has(key)) {
    const answer = look(titles, width);
    known.set(key, answer);
    answer.then((found) => found || known.delete(key));
  }
  return known.get(key);
}
