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

// Authenticated file download: plain <a href> cannot send the Authorization header.
export async function downloadAuthed(path, filename) {
  const res = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "download";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
