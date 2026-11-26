// The base map: OpenFreeMap vector tiles, restyled so names are in English (where the map data has one), black,
// and outlined so they stand out. Town and district names get a yellow highlight.
export const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
export const VECTOR_ATTRIBUTION =
  '<a href="https://openfreemap.org">OpenFreeMap</a> <a href="https://www.openmaptiles.org/">&copy; OpenMapTiles</a> ' +
  'Data from <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

// "name_en" comes after the Latin spelling because map data may fill it with the local name when there is no English one
const ENGLISH_NAME = ["coalesce", ["get", "name:en"], ["get", "name:latin"], ["get", "name_en"], ["get", "name"]];
const TEXT = "#000000";
const PLACE_HIGHLIGHT = "#ffe45c";
const OUTLINE = "#ffffff";

// labels that show a name (road number shields show "ref" and keep their own look)
const showsName = (layer) => layer.type === "symbol" && JSON.stringify(layer.layout?.["text-field"] ?? "").includes("name");

export function restyle(style) {
  return {
    ...style,
    layers: style.layers.map((layer) => {
      if (!showsName(layer)) return layer;
      const place = layer["source-layer"] === "place";
      return {
        ...layer,
        layout: { ...layer.layout, "text-field": ENGLISH_NAME },
        paint: {
          ...layer.paint,
          "text-color": TEXT,
          "text-halo-color": place ? PLACE_HIGHLIGHT : OUTLINE,
          "text-halo-width": place ? 2.5 : 2,
          "text-halo-blur": 0,
        },
      };
    }),
  };
}
