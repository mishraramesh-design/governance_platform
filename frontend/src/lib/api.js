import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API });

// Opaque bearer token held in memory + sessionStorage (survives refresh, clears on tab close).
let authToken = sessionStorage.getItem("gov_token") || null;

export function setAuthToken(token) {
  authToken = token || null;
  if (token) sessionStorage.setItem("gov_token", token);
  else sessionStorage.removeItem("gov_token");
}

export function getAuthToken() {
  return authToken;
}

api.interceptors.request.use((config) => {
  if (authToken) config.headers.Authorization = `Bearer ${authToken}`;
  return config;
});

export default api;
