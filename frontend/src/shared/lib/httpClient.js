import { translateCurrent } from './i18n.js';
import axios from 'axios';
import { UI_TESTING_MODE } from '../config/uiTestingMode.js';
import { previewAxiosAdapter } from '../preview/uiPreviewApi.js';

let resolveAccessToken = () => null;
let handleUnauthorized = () => {};

export function configureHttpClientAuth({ getAccessToken, onUnauthorized } = {}) {
  resolveAccessToken = typeof getAccessToken === 'function' ? getAccessToken : () => null;
  handleUnauthorized = typeof onUnauthorized === 'function' ? onUnauthorized : () => {};
}

const httpClient = axios.create({
  baseURL: import.meta.env?.VITE_API_BASE_URL || 'http://localhost:5000',
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
    return Promise.reject(Object.assign(new Error(translateCurrent("interfaceCopy.previewDisabled")), {
      code: "UI_TESTING_READ_ONLY",
    }));
  }
  if (token && !UI_TESTING_MODE) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

httpClient.interceptors.response.use(response => response, error => {
  // Do not discard a newer session for a failed request from an older token.
  const currentToken = resolveAccessToken();
  if (!UI_TESTING_MODE && error.response?.status === 401 && currentToken &&
      error.config?.headers?.Authorization === `Bearer ${currentToken}`) handleUnauthorized();
  return Promise.reject(error);
});
// Python's refresh endpoint is not part of the Node session contract.
export default httpClient;
