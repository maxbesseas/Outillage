import { api } from "./api.js";

let cache = null;
let teamCache = null;

export async function getAllUsers() {
  if (!cache) {
    cache = await api.get("/users");
  }
  return cache;
}

export async function getTeam() {
  if (!teamCache) {
    teamCache = await api.get("/users/team");
  }
  return teamCache;
}

export function getUserName(id) {
  if (!cache) return "-";
  const user = cache.find((u) => u.id === Number(id));
  return user ? user.full_name : "-";
}

export function invalidateUsers() {
  cache = null;
  teamCache = null;
}
