import axios from 'axios';

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
  const token = resolveAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Token refresh and unauthorized-response handling intentionally remain future
// extension points until the backend contract is defined.
export default httpClient;
