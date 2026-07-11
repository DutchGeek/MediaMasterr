import { auth } from "./stores/auth";

const UI_INDICATORS_INVALIDATE_EVENT = "reclaimerr:ui-indicators:invalidate";

const UI_INDICATOR_MUTATION_PATH_PREFIXES = [
  "/api/protection-requests",
  "/api/delete-requests",
  "/api/media/candidates/delete",
  "/api/media/candidates/move",
  "/api/info/notices",
];

function shouldInvalidateUiIndicators(url: string): boolean {
  let pathname = url;
  try {
    pathname = new URL(
      url,
      typeof window !== "undefined"
        ? window.location.origin
        : "http://localhost",
    ).pathname;
  } catch {
    // fallback to raw path
  }
  const normalizedPath = pathname.toLowerCase().split("?")[0];
  return UI_INDICATOR_MUTATION_PATH_PREFIXES.some((prefix) =>
    normalizedPath.startsWith(prefix),
  );
}

function emitUiIndicatorsInvalidate(url: string): void {
  if (typeof window === "undefined") return;
  if (!shouldInvalidateUiIndicators(url)) return;
  window.dispatchEvent(new Event(UI_INDICATORS_INVALIDATE_EVENT));
}

/**
 * make an authenticated API request
 */
export async function fetchAPI(url: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);

  // only set Content-Type for JSON requests, not for FormData (browser sets it automatically)
  if (options.body && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "include",
  });

  // handle 401 Unauthorized - token expired or invalid
  if (response.status === 401) {
    auth.logout();
    throw new Error("Session expired. Please login again.");
  }

  return response;
}

function extractErrorMessage(payload: any, fallback: string): string {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === "string" && first.trim()) return first;
    if (typeof first?.msg === "string" && first.msg.trim()) return first.msg;
  }
  if (typeof payload?.message === "string" && payload.message.trim()) {
    return payload.message;
  }
  return fallback;
}

/**
 * helper for GET requests
 */
export async function get_api<T>(
  url: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetchAPI(url, { signal });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      extractErrorMessage(
        error,
        `Request failed with status ${response.status}`,
      ),
    );
  }

  return response.json();
}

/**
 * helper for POST requests
 */
export async function post_api<T>(url: string, data?: any): Promise<T> {
  // check if data is FormData (for file uploads)
  const isFormData = data instanceof FormData;

  const response = await fetchAPI(url, {
    method: "POST",
    body:
      data === undefined ? undefined : isFormData ? data : JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      extractErrorMessage(
        error,
        `Request failed with status ${response.status}`,
      ),
    );
  }

  emitUiIndicatorsInvalidate(url);
  return response.json();
}

/**
 * helper for PUT requests
 */
export async function put_api<T>(url: string, data?: any): Promise<T> {
  const isFormData = data instanceof FormData;

  const response = await fetchAPI(url, {
    method: "PUT",
    body:
      data === undefined ? undefined : isFormData ? data : JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      extractErrorMessage(
        error,
        `Request failed with status ${response.status}`,
      ),
    );
  }

  emitUiIndicatorsInvalidate(url);
  return response.json();
}

/**
 * helper for DELETE requests
 */
export async function delete_api<T>(url: string): Promise<T> {
  const response = await fetchAPI(url, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      extractErrorMessage(
        error,
        `Request failed with status ${response.status}`,
      ),
    );
  }

  emitUiIndicatorsInvalidate(url);
  return response.json();
}
