// Un test par bug corrigé du rapport QA : chaque parcours passe par l'interface quand elle est concernée.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const accounts = () => JSON.parse(fs.readFileSync(path.join(here, "..", ".run", "comptes.json"), "utf-8"));
const ADMIN = "admin";
const MANAGER = "demo.julien.morvan";
const NANTES_MANAGER = "demo.pierre.kerbrat";
const passwordFor = (user) => (user === ADMIN ? accounts().admin : accounts().demo);

async function login(page, user) {
  await page.goto("/");
  await page.locator("#login-username").fill(user);
  await page.locator("#login-password").fill(passwordFor(user));
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#login-form")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
}

// Attend la fin du chargement de l'écran précédent : voir QA-20 dans le rapport.
async function open(page, hash) {
  await page.evaluate((h) => { location.hash = h; }, hash);
  await page.waitForLoadState("networkidle");
  await expect(page.locator("#app .section-loading")).toHaveCount(0, { timeout: 45000 });
}

async function tokenFor(request, user) {
  const response = await request.post("/auth/login", { data: { username: user, password: passwordFor(user) } });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).access_token;
}

const bearer = (token) => ({ Authorization: `Bearer ${token}` });
const toast = (page) => page.locator("#toast.visible");
const inDays = (days) => new Date(Date.now() + days * 86400000).toISOString().slice(0, 19);
let serial = 0;
const code = () => `PW-${Date.now()}-${++serial}`;

test("QA-01 : un outil au nom fait d'espaces est refusé à l'écran", async ({ page }) => {
  const consoleErrors = [];
  page.on("pageerror", (err) => consoleErrors.push(err.message));
  await login(page, MANAGER);
  await open(page, "/agence");
  await page.locator("#add-fab").click();
  await page.locator("#add-tool-btn").click();
  const form = page.locator("form:has(input[name=unique_code])");
  await form.locator("input[name=name]").fill("     ");
  await form.locator("input[name=unique_code]").fill(code());
  await form.locator("button[type=submit]").click();
  await expect(toast(page)).toContainText("Vérifiez le nom");
  expect(consoleErrors).toEqual([]);
});

test("QA-02 : montants, dates et longueurs absurdes sont refusés", async ({ request }) => {
  const token = await tokenFor(request, MANAGER);
  const post = (fields) => request.post("/agency-tools", { headers: bearer(token), data: { name: "PW", unique_code: code(), ...fields } });
  expect((await post({ purchase_price: 1e30 })).status()).toBe(422);
  expect((await post({ purchase_date: "9999-12-31T00:00:00" })).status()).toBe(422);
  expect((await post({ name: "x".repeat(100000) })).status()).toBe(422);
  expect((await post({ purchase_date: "2026-01-01T00:00:00", warranty_expiration_date: "2020-01-01T00:00:00" })).status()).toBe(422);
  expect((await post({ purchase_price: 1500 })).status()).toBe(201);
});

test("QA-03 : pas de réservation dans le passé ni sur 500 ans", async ({ request }) => {
  const token = await tokenFor(request, MANAGER);
  const tool = await (await request.post("/agency-tools", { headers: bearer(token), data: { name: "PW réservation", unique_code: code() } })).json();
  const reserve = (start, end) => request.post("/loans", { headers: bearer(token), data: { tool_id: tool.id, start_datetime: start, end_datetime_planned: end } });

  const past = await reserve(inDays(-400), inDays(-399));
  expect(past.status()).toBe(400);
  expect((await past.json()).detail).toContain("déjà passée");
  expect((await reserve(inDays(5), "2526-01-01T00:00:00")).status()).toBe(400);
  expect((await reserve(inDays(5), inDays(120))).status()).toBe(400);
  expect((await reserve(inDays(5), inDays(7))).status()).toBe(201);
});

test("QA-04 : un identifiant géant répond 404 et non 500", async ({ request }) => {
  const token = await tokenFor(request, MANAGER);
  expect((await request.get("/agency-tools/99999999999999999999", { headers: bearer(token) })).status()).toBe(404);
});

test("QA-05 : un doublon de code a un message clair", async ({ request }) => {
  const token = await tokenFor(request, MANAGER);
  const duplicate = code();
  const post = () => request.post("/agency-tools", { headers: bearer(token), data: { name: "PW doublon", unique_code: duplicate } });
  const results = await Promise.all([post(), post()]);
  const statuses = results.map((r) => r.status()).sort();
  expect(statuses).toContain(201);
  const refused = results.find((r) => r.status() !== 201);
  expect((await refused.json()).detail).toContain("existe déjà");
});

test("QA-06 : un prêt refuse un e-mail invalide et un retour passé", async ({ request }) => {
  const token = await tokenFor(request, MANAGER);
  const newTool = async () => (await (await request.post("/agency-tools", { headers: bearer(token), data: { name: "PW prêt", unique_code: code() } })).json()).id;
  const lend = async (fields) => request.post("/transfers", { headers: bearer(token), data: { agency_tool_id: await newTool(), to_external_name: "Tiers fictif", ...fields } });
  expect((await lend({ to_external_email: "pas-un-mail" })).status()).toBe(422);
  expect((await lend({ planned_return_date: inDays(-5) })).status()).toBe(400);
  expect((await lend({ to_external_email: "tiers@exemple.invalid", planned_return_date: inDays(5) })).status()).toBe(201);
});

test("QA-07 : le code de chantier doit faire 6 chiffres et rester unique", async ({ page }) => {
  await login(page, MANAGER);
  await open(page, "/chantiers");
  const submit = async (name, siteCode) => {
    await page.locator("#new-site").click();
    const form = page.locator("#s-form");
    await form.locator("input[name=name]").fill(name);
    await form.locator("input[name=code]").fill(siteCode);
    await form.locator("button[type=submit]").click();
  };
  await submit(`PW lettres ${serial++}`, "ABC");
  await expect(toast(page)).toContainText("6 chiffres");
  await page.locator("#s-form").locator("xpath=ancestor::*[.//button[@id='c']][1]").locator("#c").click();

  await submit(`PW doublon ${serial++}`, "250214");
  await expect(toast(page)).toContainText("existe déjà");
  await page.locator("#s-form").locator("xpath=ancestor::*[.//button[@id='c']][1]").locator("#c").click();

  const valid = String(100000 + (Date.now() % 800000));
  await submit(`PW valide ${serial++}`, valid);
  await expect(page.locator("#s-form")).toHaveCount(0);
  await expect(page.locator("#app")).toContainText(valid);
});

test("QA-08 : l'admin choisit l'agence avant de relire un classeur", async ({ page }) => {
  await login(page, ADMIN);
  await open(page, "/import");
  await page.locator("#imp-excel-sim").click();
  await expect(toast(page)).toContainText("Choisissez l'agence");
  await page.locator("#imp-excel-agency").selectOption("Lyon");
  await page.locator("#imp-excel-sim").click();
  await expect(toast(page)).toContainText("introuvable pour l'agence Lyon");
});

test("QA-09 : les étiquettes annoncent quand la liste est coupée", async ({ page }) => {
  await login(page, NANTES_MANAGER);
  await open(page, "/etiquettes");
  const notice = page.locator("#labels-truncated");
  await expect(notice).toContainText("2000 étiquettes affichées sur", { timeout: 45000 });
  await page.locator("#l-q").fill("DEMO-VOL-0000");
  await page.locator("#l-q").dispatchEvent("change");
  await expect(notice).toHaveCount(0, { timeout: 30000 });
  await expect(page.locator("#print-btn")).toContainText("10 étiquette");
});

test("QA-20 : un écran lent ne remplace pas l'écran demandé ensuite", async ({ page }) => {
  await login(page, MANAGER);
  await open(page, "/mes-outils");
  await page.route("**/inspections/due**", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    await route.continue();
  });
  await page.evaluate(() => { location.hash = "/"; });
  await page.waitForTimeout(200);
  await page.evaluate(() => { location.hash = "/chantiers"; });
  await expect(page.locator("#new-site")).toBeVisible();
  await page.waitForTimeout(3500);
  await expect(page.locator("#new-site")).toBeVisible();
  expect(await page.evaluate(() => location.hash)).toBe("#/chantiers");
});

const WORKER = "demo.kevin.lemoine";
const PHONE = { width: 390, height: 844 };

test("QA-10 : l'inventaire et les étiquettes restent légers avec beaucoup d'outils", async ({ page }) => {
  await login(page, NANTES_MANAGER);
  await open(page, "/inventaire");
  await page.locator('#inv-tabs button[data-tab]').last().click();
  await expect(page.locator("#inv-more")).toBeVisible({ timeout: 30000 });
  expect(await page.locator("#inv-list [data-tool-id]").count()).toBe(100);
  await page.locator("#inv-more").click();
  expect(await page.locator("#inv-list [data-tool-id]").count()).toBe(200);
  await page.locator('#inv-list [data-tool-id] [data-action="history"]').nth(150).click();
  await expect(page.locator("#history-close")).toBeVisible();
  await page.locator("#history-close").click();

  await open(page, "/controles");
  await expect(page.locator("#due-more")).toBeVisible({ timeout: 30000 });
  expect(await page.locator('#due-list [data-action="inspect"]').count()).toBe(100);
  await page.locator("#due-more").click();
  expect(await page.locator('#due-list [data-action="inspect"]').count()).toBe(200);
  await page.locator('#due-list [data-action="inspect"]').nth(150).click();
  await expect(page.locator(".modal, #modal-backdrop").first()).toBeVisible();
  await page.evaluate(() => document.getElementById("modal-backdrop")?.remove());

  await open(page, "/etiquettes");
  await expect(page.locator("#labels-preview")).toBeVisible({ timeout: 30000 });
  expect(await page.locator("#labels-sheet .label-card").count()).toBe(100);
  await page.evaluate(() => { window.print = () => { window.__printed = document.querySelectorAll("#labels-sheet .label-card").length; }; });
  await page.locator("#print-btn").click();
  await expect.poll(() => page.evaluate(() => window.__printed), { timeout: 45000 }).toBe(2000);
});

test("QA-11 : le calendrier mobile a des boutons nommés et assez grands", async ({ page }) => {
  await page.setViewportSize(PHONE);
  await login(page, MANAGER);
  await open(page, "/reservations");
  await page.locator('button[data-mode="month"]').click();
  await expect(page.locator("[data-quick-day]").first()).toBeVisible();
  const facts = await page.evaluate(() => {
    const visible = [...document.querySelectorAll("#app button")].filter((b) => b.offsetParent);
    return {
      unnamed: visible.filter((b) => !b.innerText.trim() && !b.getAttribute("aria-label")).length,
      small: visible.filter((b) => b.getBoundingClientRect().height < 32).length,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
  expect(facts).toEqual({ unnamed: 0, small: 0, overflow: 0 });
});

test.describe("écran Profil", () => {
  // L'écran attend le service worker pour connaître l'état des notifications push.
  test.use({ serviceWorkers: "allow" });

  test("QA-12 : les préférences de notification sont faciles à toucher", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await login(page, MANAGER);
    await open(page, "/mon-profil");
    const boxes = page.locator(".pref-table input[type=checkbox]");
    await expect(boxes.first()).toBeVisible();
    const smallest = await boxes.evaluateAll((list) => Math.min(...list.map((b) => b.getBoundingClientRect().height)));
    expect(smallest).toBeGreaterThanOrEqual(32);
  });
});

test("QA-13 : les champs de budget ont un libellé", async ({ page }) => {
  await login(page, "demo.claire.vautrin");
  await open(page, "/finances/budgets");
  await expect(page.getByLabel("Budget Achats")).toBeVisible();
  await expect(page.getByLabel("Année")).toBeVisible();
});

test("QA-14 : le journal d'audit est lisible", async ({ page }) => {
  await login(page, ADMIN);
  await open(page, "/audit");
  const details = page.locator(".audit-details");
  await expect(details.first()).toBeVisible();
  const text = (await details.allInnerTexts()).join(" ");
  expect(text).not.toContain("{");
  expect(text).not.toContain("null");
  expect(text).toContain(" : ");
});

test("QA-15 : le stock est fermé au personnel de chantier", async ({ request }) => {
  const worker = await tokenFor(request, WORKER);
  expect((await request.get("/stock/items", { headers: bearer(worker) })).status()).toBe(403);
  const manager = await tokenFor(request, MANAGER);
  expect((await request.get("/stock/items", { headers: bearer(manager) })).status()).toBe(200);
});

test("QA-16 : le personnel de chantier ne voit aucun prix", async ({ page, request }) => {
  const worker = await tokenFor(request, WORKER);
  const tools = await (await request.get("/agency-tools", { headers: bearer(worker) })).json();
  expect(tools.length).toBeGreaterThan(0);
  expect(tools.every((t) => t.purchase_price === null && t.daily_rate === null)).toBe(true);
  expect((await request.get("/agency-tools/export", { headers: bearer(worker) })).status()).toBe(200);

  await login(page, WORKER);
  await open(page, "/agence");
  await expect(page.locator("#items-list")).toBeVisible();
  await expect(page.locator("#export-btn")).toBeVisible();
  await expect(page.locator("#app")).not.toContainText("€");
});

test("QA-17 : le calendrier montre l'utile sans les notes des collègues", async ({ page, request }) => {
  const worker = await tokenFor(request, WORKER);
  const me = await (await request.get("/auth/me", { headers: bearer(worker) })).json();
  const loans = await (await request.get("/loans?scope=agency", { headers: bearer(worker) })).json();
  const others = loans.filter((l) => l.borrower_id !== me.id && l.created_by_id !== me.id);
  expect(others.length).toBeGreaterThan(0);
  expect(others.every((l) => l.comment === null && l.comment_return === null && l.signed_name === null && !l.has_signature)).toBe(true);
  expect(others.every((l) => l.tool_id && l.borrower_id && l.start_datetime)).toBe(true);
  expect((await request.get(`/loans/${others[0].id}/voucher.pdf`, { headers: bearer(worker) })).status()).toBe(403);

  const errors = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await login(page, WORKER);
  await open(page, "/reservations");
  await expect(page.locator("#cal-title")).toBeVisible();
  expect(errors).toEqual([]);
});

test("QA-18 : un double envoi de la connexion ne part qu'une fois", async ({ page }) => {
  const posts = [];
  page.on("request", (req) => { if (req.method() === "POST" && req.url().endsWith("/auth/login")) posts.push(req.url()); });
  await page.goto("/");
  await page.locator("#login-username").fill(MANAGER);
  await page.locator("#login-password").fill(passwordFor(MANAGER));
  await page.evaluate(() => { const form = document.querySelector("#login-form"); form.requestSubmit(); form.requestSubmit(); });
  await expect(page.locator("#login-form")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  expect(posts.length).toBe(1);
});

test("QA-19 : la réaffectation annonce ce qui va changer", async ({ page, request }) => {
  await login(page, MANAGER);
  await open(page, "/utilisateurs");
  const card = page.locator("#users-list [data-user-id]", { hasText: "Kevin Lemoine" });
  await card.locator('[data-action="reassign"]').click();
  const recap = page.locator("#reassign-recap");
  await expect(recap).toContainText("Sera transféré");
  await expect(recap).toContainText("outil(s) personnel(s)");
  await page.locator("#reassign-close").click();

  const token = await tokenFor(request, MANAGER);
  const created = await request.post("/users", {
    headers: bearer(token),
    data: { username: `pw.vide.${Date.now()}`, full_name: "PW Sans Materiel", role: "gars_chantier", password: "Passw0rd-long-12" },
  });
  expect(created.status()).toBe(201);
  await page.reload();
  await page.waitForLoadState("networkidle");
  const empty = page.locator("#users-list [data-user-id]", { hasText: "PW Sans Materiel" });
  await empty.locator('[data-action="reassign"]').click();
  await expect(page.locator("#reassign-recap")).toContainText("aucun matériel");
  await expect(page.locator('#reassign-form button[type="submit"]')).toBeDisabled();
});
