export type ServiceResult<T> =
  | { success: true; data: T; message?: string }
  | { success: false; code: string; message?: string };
