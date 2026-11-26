// A place picture. A simple drawing is always there; the photo covers it once it has loaded.
import { usePhoto } from "../../hooks/usePhoto.js";
import { safeUrl } from "../../services/format.js";

const SHAPES = {
  monument: <path d="M40 90V62h8V50c0-12 12-14 12-24 0 10 12 12 12 24v12h8v28zM22 90V48h8v42zm68 0V48h8v42z" />,
  beach: <path d="M0 74q20-9 40 0t40 0 40 0v26H0zM84 70l5-34q-14-8-22 4 10-5 19 2-14 0-17 14 9-10 17-10-3 10 1 20 3-10 0-19 10 1 15 11-1-14-14-17 8-7 18-1-7-13-21-4z" />,
  mountain: <path d="M0 90 34 38l16 24 18-34 52 62z" />,
  water: <path d="M30 62h60v10H30zm8-18h44v18H38zm14-12q8-14 16 0v12H52zM0 78q15-6 30 0t30 0 30 0 30 0v22H0z" />,
};

export function Drawing({ kind, fit = "xMidYMax slice" }) {
  return (
    <svg className={"drawing " + kind} viewBox="0 0 120 100" preserveAspectRatio={fit} aria-hidden="true">
      <circle cx="96" cy="22" r="11" className="sun" />
      <g className="land">{SHAPES[kind] || SHAPES.mountain}</g>
    </svg>
  );
}

export default function Photo({ titles, art = "mountain", alt, width = 500, credit = true, className = "", fit }) {
  const [photo, broken] = usePhoto(titles, width);
  return (
    <div className={"photo " + className}>
      <Drawing kind={art} fit={fit} />
      {photo && <img src={photo.src} alt={alt} loading="lazy" onError={broken} />}
      {photo && credit && (
        <a className="credit" href={safeUrl(photo.page)} target="_blank" rel="noopener noreferrer"
          title="Photo from Wikimedia: photographer and licence">Photo ⓘ</a>
      )}
    </div>
  );
}
