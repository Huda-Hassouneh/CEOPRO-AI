/**
 * UI-only developer preview. Vite statically replaces DEV during production builds,
 * so setting VITE_ENABLE_UI_TESTING_MODE in a production build has no effect.
 * Never treat this flag as proof of a session or as server-side authorization.
 */
export const UI_TESTING_MODE =
  import.meta.env.DEV === true &&
  import.meta.env.VITE_ENABLE_UI_TESTING_MODE === "true";
