// No tenant-scoped model evaluation endpoint exists. Do not call a nonexistent API.
export function useModelAccuracy() {
  return { data: null, isPending: false, isError: false };
}
