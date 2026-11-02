// Vérifie la cohérence du frontend : imports résolus, noms importés exportés, syntaxe, liste du service worker.
// Usage : node tools/check_frontend.mjs [dossier_frontend]
import fs from "fs";
import path from "path";
import { execFileSync } from "child_process";
import { fileURLToPath } from "url";

const root = path.resolve(process.argv[2] || path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "frontend"));
const files = [];
(function walk(d) {
  for (const f of fs.readdirSync(d)) {
    const p = path.join(d, f);
    if (fs.statSync(p).isDirectory()) walk(p);
    else if (p.endsWith(".js") && !p.endsWith("service-worker.js")) files.push(p);
  }
})(path.join(root, "js"));

let problems = 0;
const fail = (msg) => {
  problems++;
  console.log("PROBLEME", msg);
};

const exportsOf = (src) => {
  const names = new Set();
  for (const m of src.matchAll(/export\s+(?:async\s+)?(?:function\*?|const|let|class)\s+([A-Za-z0-9_$]+)/g)) names.add(m[1]);
  for (const m of src.matchAll(/export\s*\{([^}]+)\}/g)) m[1].split(",").forEach((n) => names.add(n.trim().split(/\s+as\s+/).pop()));
  return names;
};

for (const f of files) {
  const src = fs.readFileSync(f, "utf8");
  try {
    execFileSync(process.execPath, ["--check", f], { stdio: "pipe" });
  } catch (e) {
    fail(`syntaxe ${path.relative(root, f)}: ${String(e.stderr).split("\n")[0]}`);
  }
  for (const m of src.matchAll(/import\s*\{([^}]+)\}\s*from\s*"(\.[^"]+)"/g)) {
    const target = path.resolve(path.dirname(f), m[2]);
    if (!fs.existsSync(target)) {
      fail(`import introuvable ${path.relative(root, f)} -> ${m[2]}`);
      continue;
    }
    const ex = exportsOf(fs.readFileSync(target, "utf8"));
    for (const raw of m[1].split(",")) {
      const name = raw.trim().split(/\s+as\s+/)[0];
      if (name && !ex.has(name)) fail(`${path.relative(root, f)} importe '${name}' absent de ${m[2]}`);
    }
  }
}

const sw = fs.readFileSync(path.join(root, "service-worker.js"), "utf8");
const shell = new Set([...sw.matchAll(/"(\/[^"]+\.(?:js|css|png|webmanifest|html))"/g)].map((m) => m[1]));
for (const f of files) {
  const rel = "/" + path.relative(root, f).split(path.sep).join("/");
  if (!shell.has(rel)) fail(`absent de la liste du service worker : ${rel}`);
}
for (const s of shell) {
  if (!fs.existsSync(path.join(root, s))) fail(`service worker référence un fichier absent : ${s}`);
}

console.log(problems ? `${problems} problème(s)` : `Frontend cohérent (${files.length} modules, ${shell.size} fichiers en cache).`);
process.exit(problems ? 1 : 0);
