export const SAMPLE_REQUESTS = [
  "Plan a 5 day trip to Goa from Delhi in December, budget 60k for 2, love beaches and food",
  "4 days in Jaipur from Mumbai in January, 2 adults, budget 1.2 lakh, forts and shopping",
  "6 day trip to Manali from Delhi in May, family of 4, budget 1.5 lakh, adventure and nature",
  "Weekend in Kochi from Bengaluru with my wife, budget 40k",
  "3 days in Udaipur from Pune in July, budget 30k solo, relaxed pace",
  "4 days in Rishikesh from Delhi in October, budget 40k for 2, adventure and nature",
  "6 day trip to Bangkok from Mumbai in January, budget 1.8 lakh for 2, food and temples",
  "5 days in Paris from Bengaluru in June, budget 3 lakh for 2, museums and food",
  "Suggest a 4 day beach trip from Delhi in January, budget 70k for 2",
];

export const INTERESTS = ["beach", "nature", "adventure", "history", "culture", "spiritual", "food", "shopping",
  "nightlife", "relaxation", "family"];

export const MAX_TRAVELLERS = 10;

export const MODE_NAME = { flight: "Flight", train: "Train", bus: "Bus", car: "Car", bike: "Bike", ground: "Train/bus" };

export const MODE_ICON = { flight: "✈️", train: "🚆", bus: "🚌", car: "🚗", bike: "🏍️", ground: "🚆" };

// statuses where there is no plan to show: only a message, or a question back to the traveller
export const NO_PLAN_STATUSES = ["blocked", "needs_info", "cancelled"];
