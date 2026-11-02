const KEY = "outillage_theme"; // "light" | "dark" | absent (suit le système)

export function getTheme() {
  try {
    return localStorage.getItem(KEY) || "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

export function setTheme(theme) {
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // le thème reste appliqué pour la session en cours même si le stockage est indisponible
  }
  applyTheme(theme);
}

export function initTheme() {
  applyTheme(getTheme());
}
