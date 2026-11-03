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
