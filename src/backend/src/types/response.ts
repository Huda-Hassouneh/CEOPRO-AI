export interface Error {
  message: string;
  statusCode: number;
  code: string;
  details?: unknown;
}

export interface SuccessResponse<T> {
  success: true;
  message: string;
  data: T;
}

export interface ErrorResponse {
  success: false;
  error: Error;
}

export function successResponse<T>(
  data: T,
  message: string
): SuccessResponse<T> {
  return {
    success: true,
    message,
    data
  };
}

export function errorResponse(
  message: string,
  statusCode: number,
  code: string,
  details?: unknown
): ErrorResponse {
  return {
    success: false,
    error: {
      message,
      code,
      statusCode,
      ...(details !== undefined && { details })
    }
  };
}
export type ApiResponse<T> = SuccessResponse<T> | ErrorResponse;
