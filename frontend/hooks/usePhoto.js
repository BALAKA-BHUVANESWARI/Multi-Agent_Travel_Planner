import { useEffect, useState } from "react";
import { findPhoto } from "../services/photos.js";

// null until a photo is found (and again if it fails to load)
export function usePhoto(titles, width) {
  const key = titles ? titles.join("|") : "";
  const [found, setFound] = useState({ key: "", photo: null });
  useEffect(() => {
    let stale = false;
    if (key) findPhoto(key.split("|"), width).then((photo) => !stale && setFound({ key, photo }));
    return () => {
      stale = true;
    };
  }, [key, width]);
  const broken = () => setFound({ key, photo: null });
  return [found.key === key ? found.photo : null, broken];
}
