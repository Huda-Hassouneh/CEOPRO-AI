import { isIP } from "node:net";

export type SourceUrlValidationResult =
  | { success: true; data: string | undefined }
  | { success: false; message: string };

/** Validate and canonicalize the URL used as a website source identity. */
export function normalizeSourceUrl(value: unknown): SourceUrlValidationResult {
  if (value === undefined || value === null || value === "") {
    return { success: true, data: undefined };
  }
  if (typeof value !== "string" || value.trim().length > 2048) {
    return {
      success: false,
      message: "sourceUrl must be a valid URL no longer than 2048 characters."
    };
  }

  try {
    const url = new URL(value.trim());
    const hostname = url.hostname.toLowerCase().replace(/^\[|\]$/g, "");
    const isLocalHostname =
      hostname === "localhost" ||
      hostname.endsWith(".localhost") ||
      hostname.endsWith(".local") ||
      hostname.endsWith(".internal");

    if (
      !["http:", "https:"].includes(url.protocol) ||
      !hostname ||
      url.username ||
      url.password ||
      isIP(hostname) !== 0 ||
      isLocalHostname
    ) {
      return {
        success: false,
        message:
          "sourceUrl must use HTTP or HTTPS, contain no credentials, and identify a public hostname."
      };
    }

    url.hash = "";
    url.pathname = url.pathname.replace(/\/+$/, "") || "/";
    const normalized = url.toString();
    return {
      success: true,
      data: normalized.endsWith("/") ? normalized.slice(0, -1) : normalized
    };
  } catch {
    return {
      success: false,
      message: "sourceUrl must be a valid absolute HTTP or HTTPS URL."
    };
  }
}
