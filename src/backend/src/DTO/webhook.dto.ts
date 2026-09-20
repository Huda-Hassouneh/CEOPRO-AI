export type ServiceResult<T> =
  | { success: true; data: T }
  | { success: false; code: string; message?: string };
