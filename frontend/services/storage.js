// localStorage that never throws (private windows and strict settings can refuse it).
export const storage = {
  get(key) {
    try {
      return localStorage.getItem(key) || "";
    } catch {
      return "";
    }
  },
  set(key, value) {
    try {
      if (value) localStorage.setItem(key, value);
      else localStorage.removeItem(key);
    } catch {
      // not saved: the app still works for this visit
    }
  },
};
