// Under a sight in the day plan: a few photos, a gallery with the rest, and links to see more elsewhere.
import { useEffect, useState } from "react";
import { findGallery } from "../../services/gallery.js";
import PhotoViewer from "./PhotoViewer.jsx";

const SHOWN = 4;

// a flexible suggestion ("Dinner at a local restaurant") is not one particular place, so it has no pictures
export const isSight = (item) => item.type === "activity" && Boolean(item.id) && !item.id.startsWith("gen");

function useGallery(article) {
  const [found, setFound] = useState({ article: "", photos: null });
  useEffect(() => {
    let stale = false;
    if (article) findGallery(article).then((photos) => !stale && setFound({ article, photos: photos || [] }));
    return () => {
      stale = true;
    };
  }, [article]);
  return article && found.article === article ? found.photos : null;
}

export default function PlacePhotos({ name, destination, article, lookup }) {
  const photos = useGallery(article);
  const [open, setOpen] = useState(null);
  const [broken, setBroken] = useState(() => new Set());
  const shown = (photos || []).filter((p) => !broken.has(p.small));
  const waiting = lookup === "loading" || (article && photos === null);

  const search = name.toLowerCase().includes(destination.toLowerCase()) ? name : `${name} ${destination}`;
  const query = encodeURIComponent(search);
  const drop = (src) => setBroken((old) => new Set(old).add(src));

  return (
    <div className="sight-photos" data-sight={name}>
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
          <button type="button" className="see-all" onClick={() => setOpen(0)}>
            📷 View {shown.length === 1 ? "photo" : `all ${shown.length} photos`}
          </button>
        )}
        {waiting && <span className="muted">Finding photos…</span>}
        {!waiting && shown.length === 0 && (
          <span className="muted">
            {lookup === "failed" ? "Photos couldn't be loaded here." : "No confirmed photos here."}
          </span>
        )}
        <a href={`https://www.google.com/search?tbm=isch&q=${query}`} target="_blank" rel="noopener noreferrer">
          More images on Google ↗
        </a>
        <a href={`https://www.google.com/maps/search/?api=1&query=${query}`} target="_blank"
          rel="noopener noreferrer">
          Google Maps ↗
        </a>
      </div>
      {open !== null && shown.length > 0 && (
        <PhotoViewer name={name} photos={shown} start={Math.min(open, shown.length - 1)}
          onBroken={drop} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}
