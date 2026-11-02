// Parcours de bout en bout dans un vrai navigateur. Suppose un serveur neuf (voir run_e2e.py) en mode dev.
import { Browser, BASE, api, login, loginUi, sleep } from "./lib.mjs";

const b = new Browser();
const PW = "Password2026";

// ---------------------------------------------------------------- données de départ (via l'API)
const admin = (await login("admin", "admin123")).access_token;
await api("POST", "/agencies", { name: "E2E" }, admin);
const mk = async (username, role, token, extra = {}) =>
  api("POST", "/users", { username, full_name: username.toUpperCase(), role, password: PW, ...extra }, token);
await mk("dir_e2e", "directeur_agence", admin, { agency_number: "E2E" });
const dir = (await login("dir_e2e", PW)).access_token;
await mk("chef_e2e", "charge_affaires", dir);
const chef = (await login("chef_e2e", PW)).access_token;
await mk("gars_e2e", "gars_chantier", chef);
const gars = (await login("gars_e2e", PW)).access_token;
await mk("mag_e2e", "magasinier", dir);

const tool = (await api("POST", "/agency-tools", { name: "Perceuse E2E", unique_code: "E2E-PERC-1", type: "Perceuse", brand: "Bosch", purchase_price: 300, purchase_date: "2023-01-10T00:00:00" }, chef)).data;
const tool2 = (await api("POST", "/agency-tools", { name: "Meuleuse E2E", unique_code: "E2E-MEUL-1", type: "Meuleuse", purchase_price: 150 }, chef)).data;
await api("POST", "/epi", { name: "Casque E2E", unique_code: "E2E-CAS-1", type: "Casque" }, chef);
const site = (await api("POST", "/sites", { name: "Chantier E2E", client: "Client Test" }, chef)).data;
const stockItem = (await api("POST", "/stock/items", { name: "Vis E2E", quantity: 100, threshold: 10 }, chef)).data;
const kit = (await api("POST", "/kits", { name: "Kit E2E", description: "Perceuse + meuleuse", tool_ids: [tool.id, tool2.id] }, chef)).data;
await api("POST", "/personal-tools", { name: "Marteau perso", unique_code: "E2E-PERSO-1", type: "Marteau" }, gars);
if (!tool?.id || !site?.id || !stockItem?.id || !kit?.id) throw new Error("Préparation des données échouée");

await b.start();

// ---------------------------------------------------------------- 1. connexion personnel de chantier + toutes les pages
await loginUi(b, "gars_e2e", PW);
b.check("le personnel de chantier arrive sur le tableau de bord", (await b.eval("location.hash")) === "#/" && (await b.waitFor("!!document.querySelector('.stat-grid')")));
b.check("le bouton Scanner est présent dans l'en-tête", await b.eval("!!document.getElementById('scan-global')"));

const GARS_ROUTES = ["/", "/mes-outils", "/agence", "/reservations", "/transferts", "/entre-collegues", "/inventaire", "/epi", "/controles", "/notifications", "/chantiers", "/scan", "/synchronisation", "/mon-profil"];
for (const r of GARS_ROUTES) {
  await b.route("#" + r);
  await sleep(500);
  await b.waitFor("!document.querySelector('.section-loading')", r, 5000);
  const t = await b.text();
  b.check(`page ${r} s'affiche sans erreur (personnel)`, !t.includes("Une erreur est survenue") && !t.includes("Page introuvable") && t.length > 20, t.slice(0, 120));
}
b.check("le personnel n'accède pas à la maintenance des responsables (menu)", !(await b.eval("!!document.querySelector('.header-nav a[href=\"#/maintenance\"]')")));

// ---------------------------------------------------------------- 2. fiche outil, QR code, code scanné
await b.route(`#/outil/agency/${tool.id}`);
await b.waitFor("!!document.querySelector('.qr-box svg')", "fiche outil");
b.check("la fiche outil affiche le QR code", await b.eval("!!document.querySelector('.qr-box svg path')"));
b.check("la fiche outil affiche le nom et les actions", (await b.text()).includes("Perceuse E2E") && (await b.eval("!!document.querySelector('[data-a=problem]')")));
await b.route("#/code/E2E-MEUL-1");
await b.waitFor(`location.hash === '#/outil/agency/${tool2.id}'`, "redirection par code");
b.check("un code scanné redirige vers la fiche de l'outil", (await b.eval("location.hash")) === `#/outil/agency/${tool2.id}`);
await b.route("#/code/INCONNU-XYZ");
await b.waitFor("(document.querySelector('#app')?.innerText||'').includes('Aucun outil')", "code inconnu");
b.check("un code inconnu affiche un message clair", (await b.text()).includes("Aucun outil"));

// ---------------------------------------------------------------- 3. signalement en ligne puis hors ligne (file d'attente)
await b.route(`#/outil/agency/${tool.id}`);
await b.waitFor("!!document.querySelector('[data-a=problem]')");
await b.click("[data-a=problem]");
await b.waitFor("!!document.querySelector('#rp-form')", "formulaire de signalement");
await b.setInput("#rp-form [name=description]", "Mandrin bloqué (en ligne)");
await b.submit("#rp-form");
await sleep(900);
let tickets = (await api("GET", "/maintenance-tickets", undefined, chef)).data;
b.check("un signalement en ligne crée un ticket", tickets.some((t) => t.description === "Mandrin bloqué (en ligne)"));

await b.setOffline(true);
await b.click("[data-a=problem]");
await b.waitFor("!!document.querySelector('#rp-form')", "formulaire hors ligne");
await b.setInput("#rp-form [name=description]", "Câble abîmé (hors ligne)");
await b.submit("#rp-form");
await b.waitFor("(document.querySelector('#toast')?.innerText||'').includes('enregistré')", "toast hors ligne");
b.check("hors ligne, le signalement est mis en file d'attente", (await b.text("#toast")).includes("enregistré"), await b.text("#toast"));
await sleep(400);
b.check("le bandeau indique le mode hors ligne", await b.eval("!document.getElementById('sync-pill').classList.contains('hidden')"));
tickets = (await api("GET", "/maintenance-tickets", undefined, chef)).data;
b.check("le serveur n'a pas encore reçu le signalement hors ligne", !tickets.some((t) => t.description === "Câble abîmé (hors ligne)"));
await b.route("#/synchronisation");
await sleep(500);
b.check("la page Synchronisation liste l'action en attente", (await b.text()).includes("Signalement"));

await b.setOffline(false);
await b.eval("window.dispatchEvent(new Event('online'))");
await sleep(2500);
tickets = (await api("GET", "/maintenance-tickets", undefined, chef)).data;
b.check("au retour du réseau, l'action est rejouée une seule fois", tickets.filter((t) => t.description === "Câble abîmé (hors ligne)").length === 1);
await b.route("#/mes-outils");
await sleep(300);
await b.route("#/synchronisation");
await sleep(600);
b.check("la file est vide après synchronisation", (await b.text()).includes("tout est synchronisé"), await b.text());

// ---------------------------------------------------------------- 4. réservation avec chantier
await b.route("#/agence");
await b.waitFor("!!document.querySelector('[data-tool-action=reserve]')", "liste agence");
await b.eval(`(() => { const c = [...document.querySelectorAll('[data-tool-id]')].find(x => x.innerText.includes('Meuleuse E2E')); c.querySelector('[data-tool-action=reserve]').click(); return true; })()`);
await b.waitFor("!!document.querySelector('#site-select')", "select chantier");
b.check("la réservation propose les chantiers de l'agence", (await b.eval("document.querySelector('#site-select').innerText")).includes("Chantier E2E"));
await b.setInput("#site-select", String(site.id));
await b.submit("#reserve-form");
await sleep(900);
const loans = (await api("GET", "/loans", undefined, gars)).data;
b.check("la réservation est liée au chantier choisi", loans.some((l) => l.site_id === site.id && l.tool_id === tool2.id));

// ---------------------------------------------------------------- 5. connexion responsable : pages de gestion
await b.eval("localStorage.clear()");
await loginUi(b, "chef_e2e", PW);
const MANAGER_ROUTES = ["/maintenance", "/stock", "/chantiers", "/utilisation", "/finances", "/finances/actifs", "/finances/pertes", "/finances/budgets", "/exports", "/etiquettes", "/planification", "/utilisateurs", "/controles", "/garanties", "/etalonnages", "/habilitations"];
for (const r of MANAGER_ROUTES) {
  await b.route("#" + r);
  await sleep(600);
  await b.waitFor("!document.querySelector('.section-loading')", r, 6000);
  const t = await b.text();
  b.check(`page ${r} s'affiche sans erreur (responsable)`, !t.includes("Une erreur est survenue") && !t.includes("Accès non autorisé") && !t.includes("Page introuvable") && t.length > 20, t.slice(0, 160));
}

// maintenance : faire avancer un ticket
await b.route("#/maintenance");
await b.waitFor("!!document.querySelector('.card[data-id]')", "tickets");
await b.click(".card[data-id]");
await b.waitFor("!!document.querySelector('#tr-form')", "détail ticket");
await b.setInput("#tr-form [name=status]", "diagnostic");
await b.submit("#tr-form");
await sleep(900);
tickets = (await api("GET", "/maintenance-tickets", undefined, chef)).data;
b.check("un responsable fait avancer un ticket depuis l'interface", tickets.some((t) => t.status === "diagnostic"));

// étiquettes : QR + code-barres
await b.route("#/etiquettes");
await b.waitFor("!!document.querySelector('.label-card')", "étiquettes");
b.check("les étiquettes contiennent un QR code et un code-barres", (await b.eval("document.querySelectorAll('.label-card .label-qr svg').length")) >= 1 && (await b.eval("document.querySelectorAll('.label-card .label-bar svg').length")) >= 1);

// chantier : fiche avec coût
await b.route("#/chantiers");
await b.waitFor("!!document.querySelector('.card[data-id]')", "chantiers");
await b.click(".card[data-id]");
await b.waitFor("(document.querySelector('.modal')?.innerText||'').includes('Coût')", "fiche chantier");
b.check("la fiche chantier affiche le coût d'usage", (await b.text(".modal")).includes("Coût d'usage"), await b.text(".modal"));
await b.click("#c");

// finances : téléchargements (Excel + CSV) via l'API depuis la session
const dl = await b.eval(`(async () => {
  const s = JSON.parse(localStorage.getItem('outillage_session'));
  const out = {};
  for (const [k, u] of [['csv', '/exports/tools?format=csv'], ['xlsx', '/exports/workbook']]) {
    const r = await fetch(u, { headers: { Authorization: 'Bearer ' + s.token } });
    out[k] = [r.status, (await r.arrayBuffer()).byteLength];
  }
  return out;
})()`);
b.check("les exports CSV et Excel se téléchargent", dl.csv[0] === 200 && dl.csv[1] > 50 && dl.xlsx[0] === 200 && dl.xlsx[1] > 1000, JSON.stringify(dl));

// ---------------------------------------------------------------- 5a. recherche globale
await b.route("#/");
await b.waitFor("!!document.getElementById('search-global')", "bouton recherche");
await b.click("#search-global");
await b.waitFor("!!document.querySelector('#gs-input')", "modale de recherche");
await b.setInput("#gs-input", "Meuleuse E2E");
await b.waitFor("(document.querySelector('#gs-results')?.innerText||'').includes('Meuleuse E2E')", "résultat de recherche", 5000);
b.check("la recherche globale trouve un outil par son nom", (await b.text("#gs-results")).includes("Meuleuse E2E"));
await b.click(".search-result");
await b.waitFor(`location.hash === '#/outil/agency/${tool2.id}'`, "navigation depuis un résultat");
b.check("cliquer un résultat ouvre la fiche de l'outil", (await b.eval("location.hash")) === `#/outil/agency/${tool2.id}`);

// ---------------------------------------------------------------- 5b. thème sombre et confirmations sans window.confirm()
await b.route("#/mon-profil");
await b.waitFor("!!document.querySelector('#theme-select')", "sélecteur de thème");
b.check("le thème est clair par défaut", (await b.eval("document.documentElement.getAttribute('data-theme')")) === "light");
await b.setInput("#theme-select", "dark");
await sleep(200);
b.check("basculer sur sombre pose data-theme=dark", (await b.eval("document.documentElement.getAttribute('data-theme')")) === "dark");
await b.eval("location.reload()");
await b.waitFor("!!document.querySelector('.header-nav')", "rechargement");
b.check("le thème sombre survit au rechargement (localStorage)", (await b.eval("document.documentElement.getAttribute('data-theme')")) === "dark");
await b.route("#/mon-profil");
await b.waitFor("!!document.querySelector('#theme-select')");
await b.setInput("#theme-select", "light");
await sleep(200);

await b.route("#/planification");
await b.waitFor("!!document.querySelector('#plan-tabs')", "onglets planification");
await b.click('[data-tab="kits"]');
await b.waitFor("!!document.querySelector('[data-del]')", "bouton supprimer un kit");
await b.click("[data-del]");
await b.waitFor("!!document.querySelector('#confirm-no')", "modale de confirmation");
b.check("la suppression passe par une modale, pas window.confirm()", await b.eval("!!document.querySelector('#confirm-yes') && !!document.querySelector('.modal')"));
await b.click("#confirm-no");
await sleep(400);
let kitsList = (await api("GET", "/kits", undefined, chef)).data;
b.check("annuler la modale ne supprime rien", kitsList.some((k) => k.id === kit.id));
await b.click("[data-del]");
await b.waitFor("!!document.querySelector('#confirm-yes')", "modale de confirmation (2)");
await b.click("#confirm-yes");
await sleep(400);
kitsList = (await api("GET", "/kits", undefined, chef)).data;
b.check("confirmer la modale supprime le kit", !kitsList.some((k) => k.id === kit.id));

// ---------------------------------------------------------------- 6. déconnexion et console
await b.click("#logout-btn");
await b.waitFor("location.hash === '#/login'");
b.check("la déconnexion ramène à la connexion", (await b.eval("location.hash")) === "#/login");

const csp = b.consoleProblems.filter((p) => /Content Security Policy|Refused to/i.test(p));
b.check("aucune violation de CSP dans la console", csp.length === 0, csp.join(" | "));
const other = b.consoleProblems.filter((p) => !/Content Security Policy|Refused to|40[0-9]|429|Failed to load resource|ERR_INTERNET_DISCONNECTED|Failed to fetch/i.test(p));
b.check("aucune exception JavaScript inattendue", other.length === 0, other.join(" | "));
if (b.consoleProblems.length) console.log("\nConsole :\n - " + b.consoleProblems.join("\n - "));

process.exit(b.finish() ? 1 : 0);
