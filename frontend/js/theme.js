const KEY = "outillage_theme"; // "light" | "dark" | "system" ; absent : clair

export function getTheme() {
  try {
    return localStorage.getItem(KEY) || "light";
  } catch {
    return "light";
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
    localStorage.setItem(KEY, theme);
  } catch {
    // le thème reste appliqué pour la session en cours même si le stockage est indisponible
  }
  applyTheme(theme);
}

export function initTheme() {
  applyTheme(getTheme());
}
