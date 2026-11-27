// A flexible suggestion ("Dinner at a local restaurant") is not one particular place. It gets example photos of that
// kind of thing, from a Wikipedia article on the topic, always labelled as examples, plus a map search that finds
// real places of that kind at the destination.
const KINDS = {
  "gen-dinner": {
    note: "Example photos of the country's food, not a particular restaurant.",
    articles: (country) => [
      ...(country ? [`Cuisine of ${country}`, `Cuisine of the ${country}`] : []), "Restaurant",
    ],
    find: "restaurants",
  },
  "gen-market": {
    note: "Example photos of street food from around the world, not a particular market.",
    articles: () => ["Street food"],
    find: "markets and street food",
  },
  "gen-cafe": {
    note: "Example photos of cafés from around the world, not a particular café.",
    articles: () => ["Coffeehouse"],
    find: "cafes",
  },
  "gen-sunset": {
    note: "Example sunset photos, not a particular viewpoint.",
    articles: () => ["Sunset"],
    find: "parks and viewpoints",
  },
  "gen-museum": {
    note: "Example museum photos from around the world, not a particular museum.",
    articles: () => ["Museum"],
    find: "museums",
  },
  "gen-walk": {
    note: "Photos from around the destination, not a set walking route.",
    articles: (country, town) => (town ? [town] : []), // only the article the server confirmed by its location
    find: "walking tours",
  },
  "generic-indoor": {
    note: "Example photos of cafés from around the world, not a particular place.",
    articles: () => ["Coffeehouse"],
    find: "cafes, spas and museums",
  },
};

export const MAX_EXAMPLES = 8;

export const exampleKind = (id) => KINDS[id] || null;
