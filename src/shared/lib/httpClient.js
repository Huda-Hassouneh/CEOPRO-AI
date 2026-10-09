import axios from 'axios';
import { UI_TESTING_MODE } from '../config/uiTestingMode.js';
import { previewAxiosAdapter } from '../preview/uiPreviewApi.js';

let resolveAccessToken = () => null;

export function configureHttpClientAuth({ getAccessToken } = {}) {
  resolveAccessToken = typeof getAccessToken === 'function' ? getAccessToken : () => null;
}

const httpClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000',
  headers: {
    'Content-Type': 'application/json',
  },
});

httpClient.interceptors.request.use((config) => {
  // The preview never uses the network, even for read requests. Isolate
  // unauthenticated UI inspection from test/production databases completely.
  if (UI_TESTING_MODE) {
    config.adapter = previewAxiosAdapter;
    delete config.headers.Authorization;
  }
  const token = resolveAccessToken();
  if (UI_TESTING_MODE && !["get", "head", "options"].includes(String(config.method || "get").toLowerCase())) {
    // UI preview is read-only. Never submit payments, imports, or edits to the backend.
    return Promise.reject(Object.assign(new Error("Actions are disabled in UI testing preview"), {
      code: "UI_TESTING_READ_ONLY",
    }));
  }
  if (token && !UI_TESTING_MODE) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Token refresh and unauthorized-response handling intentionally remain future
// extension points until the backend contract is defined.
export default httpClient;
