import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

export const AUTH_TOKEN_KEY = 'audit_auth_token';
export const AUTH_USER_KEY = 'audit_auth_user';

export const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach Authorization Bearer token to all outgoing requests if present
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor to handle 401 unauthenticated errors centrally
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response && error.response.status === 401) {
      // Avoid redirect loop if the 401 occurred on the login endpoint itself
      const requestUrl = error.config?.url || '';
      if (!requestUrl.includes('/auth/login')) {
        localStorage.removeItem(AUTH_TOKEN_KEY);
        localStorage.removeItem(AUTH_USER_KEY);
        // Dispatch custom auth-expired event for React context listener
        window.dispatchEvent(new CustomEvent('auth:expired'));
      }
    }
    return Promise.reject(error);
  }
);
