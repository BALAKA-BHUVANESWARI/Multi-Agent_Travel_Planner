// Under a sight in the day plan: a few photos, a gallery with the rest, and links to see more elsewhere. A flexible
// suggestion gets the same row with example photos, clearly labelled.
import { useEffect, useState } from "react";
import { MAX_EXAMPLES } from "../../services/examplePhotos.js";
import { findFirstGallery } from "../../services/gallery.js";
import PhotoViewer from "./PhotoViewer.jsx";

const SHOWN = 4;

// a flexible suggestion ("Dinner at a local restaurant") is not one particular place
export const isSight = (item) => item.type === "activity" && Boolean(item.id) && !item.id.startsWith("gen");

// the photos of the first of these articles that has any; null while looking
function useGallery(articles) {
  const key = articles.join("|");
  const [found, setFound] = useState({ key: "", photos: null });
  useEffect(() => {
    let stale = false;
    if (key) findFirstGallery(key.split("|")).then((photos) => !stale && setFound({ key, photos }));
    return () => {
      stale = true;
    };
  }, [key]);
  return key && found.key === key ? found.photos : null;
}

// the thumbnails and the full-screen viewer, for a real sight or for examples
function Gallery({ name, articles, limit, waitingFor, empty, seeAll, children }) {
  const photos = useGallery(articles);
  const [open, setOpen] = useState(null);
  const [broken, setBroken] = useState(() => new Set());
  const shown = (photos || []).slice(0, limit).filter((p) => !broken.has(p.small));
  const waiting = waitingFor || (articles.length > 0 && photos === null);
  const drop = (src) => setBroken((old) => new Set(old).add(src));

  return (
    <>
      {shown.length > 0 && (
        <div className="thumbs">
          {shown.slice(0, SHOWN).map((photo, i) => (
            <button type="button" key={photo.small} onClick={() => setOpen(i)}
              aria-label={`Open photo ${i + 1} of ${shown.length} of ${name}`}>
              <img src={photo.small} alt={photo.caption || `${name}, photo ${i + 1}`} loading="lazy"
                onError={() => drop(photo.small)} />
              {i === SHOWN - 1 && shown.length > SHOWN && <span className="more">+{shown.length - SHOWN}</span>}
            </button>
          ))}
        </div>
      )}
      <div className="photo-links">
        {shown.length > 0 && (
          <button type="button" className="see-all" onClick={() => setOpen(0)}>📷 {seeAll(shown.length)}</button>
        )}
        {waiting && <span className="muted">Finding photos…</span>}
        {!waiting && shown.length === 0 && <span className="muted">{empty}</span>}
        {children}
      </div>
      {open !== null && shown.length > 0 && (
        <PhotoViewer name={name} photos={shown} start={Math.min(open, shown.length - 1)}
          onBroken={drop} onClose={() => setOpen(null)} />
      )}
    </>
  );
}

function Outside({ href, children }) {
  return <a href={href} target="_blank" rel="noopener noreferrer">{children} ↗</a>;
}

const images = (query) => `https://www.google.com/search?tbm=isch&q=${encodeURIComponent(query)}`;
const maps = (query) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;

export function ExamplePhotos({ name, destination, country, kind, town, lookup }) {
  const articles = kind.articles(country, town);
  // only the walking suggestion waits for the server, which confirms the destination's article
  const waitingFor = articles.length === 0 && lookup === "loading";
  return (
    <div className="sight-photos examples" data-example={name}>
      <div className="example-note muted">{kind.note}</div>
      <Gallery name={`${name} (example photos)`} articles={articles} limit={MAX_EXAMPLES} waitingFor={waitingFor}
        empty="No example photos here." seeAll={(n) => `View ${n === 1 ? "example photo" : `${n} example photos`}`}>
        <Outside href={maps(`${kind.find} in ${destination}`)}>Find {kind.find} in {destination}</Outside>
      </Gallery>
    </div>
  );
}

export default function PlacePhotos({ name, destination, article, lookup }) {
  const search = name.toLowerCase().includes(destination.toLowerCase()) ? name : `${name} ${destination}`;
  return (
    <div className="sight-photos" data-sight={name}>
      <Gallery name={name} articles={article ? [article] : []} limit={undefined} waitingFor={lookup === "loading"}
        empty={lookup === "failed" ? "Photos couldn't be loaded here." : "No confirmed photos here."}
        seeAll={(n) => `View ${n === 1 ? "photo" : `all ${n} photos`}`}>
        <Outside href={images(search)}>More images on Google</Outside>
        <Outside href={maps(search)}>Google Maps</Outside>
      </Gallery>
    </div>
  );
}
