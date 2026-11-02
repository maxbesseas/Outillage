export const TYPE_CATEGORIES = [
  "Electroportatif",
  "Outillage manuel",
  "Moyens d'accès en hauteur",
  "Outils de mesure",
];

export const NAME_TO_TYPE = {
  "disqueuse": "Electroportatif",
  "dérouleuse": "Electroportatif",
  "derouleuse": "Electroportatif",
  "échafaudage": "Moyens d'accès en hauteur",
  "echafaudage": "Moyens d'accès en hauteur",
  "échelle": "Moyens d'accès en hauteur",
  "echelle": "Moyens d'accès en hauteur",
  "enrouleur": "Electroportatif",
  "escabeau 3 marches": "Moyens d'accès en hauteur",
  "escabeau 4 marches": "Moyens d'accès en hauteur",
  "escabeau 5 marches": "Moyens d'accès en hauteur",
  "escabeau 7 marches": "Moyens d'accès en hauteur",
  "escabeaux 3 marches": "Moyens d'accès en hauteur",
  "escabeaux 4 marches": "Moyens d'accès en hauteur",
  "escabeaux 5 marches": "Moyens d'accès en hauteur",
  "escabeaux 7 marches": "Moyens d'accès en hauteur",
  "multimètre": "Outils de mesure",
  "multimetre": "Outils de mesure",
  "perforateur": "Electroportatif",
  "pince à sertir": "Outillage manuel",
  "pince a sertir": "Outillage manuel",
  "pince ampèremétrique": "Outils de mesure",
  "pince amperemetrique": "Outils de mesure",
  "pirl": "Outils de mesure",
  "scie oscillo-battante": "Electroportatif",
  "scie oscillobattante": "Electroportatif",
  "scie radiale": "Electroportatif",
  "scie sabre": "Electroportatif",
  "tri pack intérim": "Moyens d'accès en hauteur",
  "tri pack interim": "Moyens d'accès en hauteur",
  "vat": "Outils de mesure",
  "visseuse": "Electroportatif",
};

export function wireTypeAutocomplete(nameInput, typeInput) {
  nameInput.addEventListener("input", () => {
    if (typeInput.value.trim()) return;
    const key = nameInput.value.trim().toLowerCase();
    if (NAME_TO_TYPE[key]) {
      typeInput.value = NAME_TO_TYPE[key];
    }
  });
}
