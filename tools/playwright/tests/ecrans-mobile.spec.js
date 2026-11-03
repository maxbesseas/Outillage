// Tous les écrans sur téléphone, pour chaque profil : boutons nommés et assez grands, champs libellés, pas de débordement.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const accounts = () => JSON.parse(fs.readFileSync(path.join(here, "..", ".run", "comptes.json"), "utf-8"));

const MIN_HEIGHT = 32;
const ROUTES = ["/", "/mes-outils", "/agence", "/reservations", "/transferts", "/entre-collegues", "/utilisateurs", "/finances", "/finances/actifs", "/finances/pertes", "/finances/budgets",
  "/exports", "/inventaire", "/epi", "/etiquettes", "/garanties", "/parametres", "/audit", "/taches", "/notifications", "/controles", "/periodicites", "/etalonnages", "/habilitations",
  "/planification", "/maintenance", "/chantiers", "/utilisation", "/import", "/sauvegardes", "/assistant-suivi", "/stock", "/scan", "/synchronisation", "/mon-profil", "/charte"];
const PROFILES = [["admin", "admin"], ["directrice", "demo.claire.vautrin"], ["chantier", "demo.kevin.lemoine"]];

const measure = (minHeight) => {
  const describe = (e) => `${e.tagName.toLowerCase()}${e.id ? `#${e.id}` : ""}${e.name ? `[${e.name}]` : ""}${e.className && typeof e.className === "string" ? `.${e.className.split(" ")[0]}` : ""} « ${(e.innerText || e.placeholder || "").trim().slice(0, 20)} »`;
  const visible = (e) => e.offsetParent !== null && e.getBoundingClientRect().width > 0;
  const controls = [...document.querySelectorAll("#app button, #app a.btn, #app input:not([type=hidden]), #app select, #app textarea")].filter(visible);
  const small = controls.filter((e) => e.getBoundingClientRect().height < minHeight).map(describe);
  const unnamed = [...document.querySelectorAll("#app button")].filter(visible).filter((e) => !(e.innerText || "").trim() && !e.getAttribute("aria-label") && !e.title).map(describe);
  const unlabeled = [...document.querySelectorAll("#app input:not([type=hidden]), #app select, #app textarea")].filter(visible).filter((e) => !e.labels?.length && !e.getAttribute("aria-label") && !e.getAttribute("aria-labelledby")).map(describe);
  return { small, unnamed, unlabeled, overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, nodes: document.querySelectorAll("*").length };
};

test.use({ serviceWorkers: "allow", viewport: { width: 390, height: 844 } });

for (const [profile, username] of PROFILES) {
  test(`écrans mobiles : ${profile}`, async ({ page }) => {
    test.setTimeout(240000);
    await page.goto("/");
    await page.locator("#login-username").fill(username);
    await page.locator("#login-password").fill(username === "admin" ? accounts().admin : accounts().demo);
    await page.locator("#login-form button[type=submit]").click();
    await expect(page.locator("#login-form")).toHaveCount(0);
    await page.waitForLoadState("networkidle");

    const problems = [];
    for (const route of ROUTES) {
      await page.evaluate((h) => { location.hash = h; }, route);
      await expect(page.locator("#app .section-loading")).toHaveCount(0, { timeout: 30000 });
      await page.waitForLoadState("networkidle");
      // L'application pose les libellés à l'image suivante (startAccessibleForms).
      await page.waitForTimeout(400);
      const m = await page.evaluate(measure, MIN_HEIGHT);
      if (m.small.length || m.unnamed.length || m.unlabeled.length || m.overflow > 0 || m.nodes > 15000) problems.push({ route, ...m, small: [...new Set(m.small)], unnamed: [...new Set(m.unnamed)], unlabeled: [...new Set(m.unlabeled)] });
    }
    if (problems.length) console.log(`PROBLEMES ${profile} ${JSON.stringify(problems)}`);
    expect(problems).toEqual([]);
  });
}
