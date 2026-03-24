export interface PaginationMeta {
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface SuccessResponse<T> {
  data: T;
  meta?: PaginationMeta;
}

export interface ErrorResponse {
  error: string;
  detail?: string;
  code?: string;
}
