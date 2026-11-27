// The gallery: one large photo, arrows (or the keyboard) to move, and all the others below. Esc closes it.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { safeUrl } from "../../services/format.js";

export default function PhotoViewer({ name, photos, start, onBroken, onClose }) {
  const [index, setIndex] = useState(start);
  const [small, setSmall] = useState(() => new Set()); // photos with no large copy
  const ref = useRef(null);
  const at = Math.min(index, photos.length - 1);
  const photo = photos[at];
  const move = (step) => setIndex((at + step + photos.length) % photos.length);
  // no large copy: show the small one. If that fails too, the picture is taken out of the gallery.
  const failed = () => (small.has(photo.large) ? onBroken(photo.small)
    : setSmall((old) => new Set(old).add(photo.large)));

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog.open) dialog.showModal(); // keeps the keyboard inside the gallery
  }, []);

  const keys = (e) => {
    if (e.key === "ArrowRight") move(1);
    if (e.key === "ArrowLeft") move(-1);
  };

  return createPortal(
    <dialog className="viewer" ref={ref} onClose={onClose} onKeyDown={keys} aria-label={`Photos of ${name}`}
      onClick={(e) => e.target === ref.current && ref.current.close()}>
      <div className="viewer-head">
        <h3>{name}</h3>
        <button type="button" className="close" onClick={() => ref.current.close()}>✕ Close</button>
      </div>
      <div className="viewer-stage">
        <img key={photo.large} src={small.has(photo.large) ? photo.small : photo.large}
          alt={photo.caption || `${name}, photo ${at + 1}`}
          onError={failed} />
        {photos.length > 1 && (
          <>
            <button type="button" className="prev" aria-label="Previous photo" onClick={() => move(-1)}>‹</button>
            <button type="button" className="next" aria-label="Next photo" onClick={() => move(1)}>›</button>
          </>
        )}
      </div>
      <div className="viewer-caption">
        <span><b>{at + 1} / {photos.length}</b>{photo.caption ? ` · ${photo.caption}` : ""}</span>
        <a href={safeUrl(photo.page)} target="_blank" rel="noopener noreferrer">Photographer and licence ↗</a>
      </div>
      <div className="viewer-grid">
        {photos.map((p, i) => (
          <button type="button" key={p.small} aria-current={i === at} aria-label={`Photo ${i + 1}`}
            onClick={() => setIndex(i)}>
            <img src={p.small} alt="" loading="lazy" onError={() => onBroken(p.small)} />
          </button>
        ))}
      </div>
      <p className="viewer-note">
        Photos come from this place's Wikipedia article, so some may show its history. They are not live views.
      </p>
    </dialog>,
    document.body,
  );
}
