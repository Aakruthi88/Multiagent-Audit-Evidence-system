import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { AuthUser, AuthState } from '../types/auth';
import { AUTH_TOKEN_KEY, AUTH_USER_KEY } from '../api/client';
import { loginUser, getCurrentUser } from '../api/endpoints';

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
  clearError: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(AUTH_TOKEN_KEY));
  const [user, setUser] = useState<AuthUser | null>(() => {
    const savedUser = localStorage.getItem(AUTH_USER_KEY);
    if (savedUser) {
      try {
        return JSON.parse(savedUser);
      } catch {
        return null;
      }
    }
    return null;
  });
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const logout = useCallback(() => {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
    setToken(null);
    setUser(null);
    setError(null);
  }, []);

  // Listen for centralized 401 token expiration events from Axios interceptor
  useEffect(() => {
    const handleAuthExpired = () => {
      logout();
    };

    window.addEventListener('auth:expired', handleAuthExpired);
    return () => {
      window.removeEventListener('auth:expired', handleAuthExpired);
    };
  }, [logout]);

  // Initial session restoration
  useEffect(() => {
    const initAuth = async () => {
      const storedToken = localStorage.getItem(AUTH_TOKEN_KEY);
      if (!storedToken) {
        setIsLoading(false);
        return;
      }

      try {
        const currentUser = await getCurrentUser();
        setUser(currentUser);
        localStorage.setItem(AUTH_USER_KEY, JSON.stringify(currentUser));
      } catch (err: any) {
        // If token is invalid or expired, clear state
        console.warn('[Auth] Session validation failed, logging out.');
        localStorage.removeItem(AUTH_TOKEN_KEY);
        localStorage.removeItem(AUTH_USER_KEY);
        setToken(null);
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    };

    initAuth();
  }, []);

  const login = async (email: string, password: string): Promise<{ success: boolean; error?: string }> => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await loginUser({ email: email.trim(), password });
      const { access_token, user: authUser } = response;

      localStorage.setItem(AUTH_TOKEN_KEY, access_token);
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(authUser));

      setToken(access_token);
      setUser(authUser);
      setIsLoading(false);
      return { success: true };
    } catch (err: any) {
      setIsLoading(false);
      let errorMsg = 'An error occurred during authentication.';
      if (err.response) {
        if (err.response.status === 401) {
          errorMsg = err.response.data?.detail || 'Incorrect email or password.';
        } else if (err.response.status === 403) {
          errorMsg = 'Access forbidden. Your account is not authorized.';
        } else {
          errorMsg = err.response.data?.detail || `Server error (${err.response.status}).`;
        }
      } else if (err.request) {
        errorMsg = 'Unable to connect to authentication server. Please check backend status.';
      }
      setError(errorMsg);
      return { success: false, error: errorMsg };
    }
  };

  const clearError = () => setError(null);

  const isAuthenticated = !!token && !!user;

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated,
        isLoading,
        error,
        login,
        logout,
        clearError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
