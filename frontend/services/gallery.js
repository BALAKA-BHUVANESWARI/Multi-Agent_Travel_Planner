// Many photos of one place: the pictures in its Wikipedia article, in the article's order, loaded by the visitor's
// browser. Maps, plans, logos and drawings are left out. Old views and pictures of fires or repair work go last,
// because a traveller wants to see what the place looks like. Every photo links to its file page (author, licence).
import { filePage, isPicture } from "./photos.js";

const MEDIA = "https://en.wikipedia.org/api/rest_v1/page/media-list/";
export const MAX_PHOTOS = 24;
const AT_ONCE = 4;

const NOT_PHOTO = new RegExp("(^|[^a-z])(logo|flag|map|maps|plan|plans|locator|coat of arms|blason|diagram|section|" +
  "coupe|signature|icon|engraving|etching|painting|drawing|lithograph|gravure|dessin|sketch|portrait|model)([^a-z]|$)");
const LESS_USEFUL = /(^|[^a-z])(fire|burning|flames|feu|incendie|damage|damaged|scaffold|scaffolding)([^a-z]|$)/;
const OLD_YEAR = /(^|[^0-9])(1[0-8]\d\d|19[0-6]\d)([^0-9]|$)/;
const NEW_YEAR = /(19[7-9]\d|20\d\d)/;

function toPhoto(entry) {
  const source = entry.srcset?.[0]?.src;
  if (entry.type !== "image" || entry.showInGallery === false || !source) return null;
  const url = new URL(source, "https://en.wikipedia.org");
  if (!/\.jpe?g$/i.test(url.pathname) || !isPicture(url.href)) return null;
  const file = String(entry.title || "").replace(/^File:/, "");
  const caption = String(entry.caption?.text || "").trim();
  const words = `${file.replace(/\.jpe?g$/i, "")} ${caption}`.replace(/_/g, " ").toLowerCase();
  if (NOT_PHOTO.test(words)) return null;
  // Wikimedia serves only some widths: 500 and 1280 are among them. A picture narrower than 1280 has no copy that
  // size, so the viewer falls back to the 500 one.
  const sized = (width) => url.href.replace(/\/\d+px-/, `/${width}px-`);
  return {
    small: sized(500), large: sized(1280), caption, page: filePage(url.href.split("?")[0]),
    later: LESS_USEFUL.test(words) || (OLD_YEAR.test(words) && !NEW_YEAR.test(words)),
  };
}

export function choosePhotos(items) {
  const photos = [];
  const seen = new Set();
  for (const entry of items || []) {
    const photo = toPhoto(entry);
    if (photo && !seen.has(photo.small)) {
      seen.add(photo.small);
      photos.push(photo);
    }
  }
  return [...photos.filter((p) => !p.later), ...photos.filter((p) => p.later)].slice(0, MAX_PHOTOS);
}

// a long plan asks about many places: only a few requests go out at a time
let running = 0;
const queue = [];
async function inTurn(job) {
  if (running >= AT_ONCE) await new Promise((resolve) => queue.push(resolve));
  else running += 1;
  try {
    return await job();
  } finally {
    const next = queue.shift();
    if (next) next();
    else running -= 1;
  }
}

const known = new Map();

export function findGallery(article) {
  if (!known.has(article)) {
    const answer = inTurn(async () => {
      try {
        const response = await fetch(MEDIA + encodeURIComponent(article.replace(/ /g, "_")));
        if (!response.ok) return null;
        return choosePhotos((await response.json()).items);
      } catch {
        return null; // offline or blocked
      }
    });
    known.set(article, answer);
    answer.then((photos) => photos || known.delete(article));
  }
  return known.get(article);
}
