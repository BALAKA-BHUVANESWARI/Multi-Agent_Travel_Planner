// Ten popular places in India for the home page. This is a hand-picked list, not an official ranking.
// "best" and "days" are rough hand-written guidance. `photos` are Wikipedia articles whose lead picture is used;
// `art` picks the drawing shown when no photo can be loaded.
export const INDIA_DESTINATIONS = [
  { name: "Agra", state: "Uttar Pradesh", highlight: "Taj Mahal", months: [10, 11, 12, 1, 2, 3], best: "Oct–Mar",
    days: 2, likes: ["history", "culture"], photos: ["Taj Mahal"], art: "monument" },
  { name: "Jaipur", state: "Rajasthan", highlight: "Forts and palaces", months: [10, 11, 12, 1, 2, 3],
    best: "Oct–Mar", days: 3, likes: ["history", "shopping"], photos: ["Hawa Mahal", "Amber Fort"], art: "monument" },
  { name: "Goa", state: "Goa", highlight: "Beaches", months: [11, 12, 1, 2], best: "Nov–Feb", days: 4,
    likes: ["beach", "nightlife"], photos: ["Palolem Beach", "Anjuna", "Goa"], art: "beach" },
  { name: "Delhi", state: "Delhi", highlight: "Monuments and food", months: [10, 11, 12, 1, 2, 3], best: "Oct–Mar",
    days: 3, likes: ["history", "food"], photos: ["India Gate", "Humayun's Tomb"], art: "monument" },
  { name: "Alleppey", state: "Kerala", highlight: "Backwaters", months: [11, 12, 1, 2], best: "Nov–Feb", days: 3,
    likes: ["nature", "relaxation"], photos: ["Kerala backwaters", "Alappuzha"], art: "water" },
  { name: "Varanasi", state: "Uttar Pradesh", highlight: "Ganga ghats", months: [10, 11, 12, 1, 2, 3],
    best: "Oct–Mar", days: 3, likes: ["spiritual", "culture"], photos: ["Ghats in Varanasi", "Varanasi"], art: "water" },
  { name: "Udaipur", state: "Rajasthan", highlight: "City of lakes", months: [9, 10, 11, 12, 1, 2, 3],
    best: "Sep–Mar", days: 3, likes: ["history", "relaxation"], photos: ["Lake Palace", "City Palace, Udaipur"], art: "water" },
  { name: "Amritsar", state: "Punjab", highlight: "Golden Temple", months: [10, 11, 12, 1, 2, 3], best: "Oct–Mar",
    days: 2, likes: ["spiritual", "food"], photos: ["Golden Temple"], art: "monument" },
  { name: "Manali", state: "Himachal Pradesh", highlight: "Mountains", months: [3, 4, 5, 6], best: "Mar–Jun",
    days: 4, likes: ["adventure", "nature"], photos: ["Solang Valley", "Manali, Himachal Pradesh"], art: "mountain" },
  { name: "Leh", state: "Ladakh", highlight: "High-altitude lakes", months: [6, 7, 8, 9], best: "Jun–Sep", days: 6,
    likes: ["adventure", "nature"], photos: ["Pangong Tso", "Leh"], art: "mountain" },
];

export const findDestination = (name) =>
  INDIA_DESTINATIONS.find((d) => d.name.toLowerCase() === String(name ?? "").trim().toLowerCase());
