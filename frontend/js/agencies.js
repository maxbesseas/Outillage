import { api } from "./api.js";

let cache = null;

export async function getAgencies(force = false) {
  if (!cache || force) {
    cache = await api.get("/agencies");
  }
  return cache;
}

export function invalidateAgencies() {
  cache = null;
}
