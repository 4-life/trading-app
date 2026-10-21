import type { ApiResult } from "@/lib/api";

// One form intent's handler: the API call it makes.
export type ActionHandler = (request: Request, form: FormData) => Promise<ApiResult<unknown>>;
