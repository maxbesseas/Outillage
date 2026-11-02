export const ROLE_LABELS = {
  gars_chantier: "Personnel de chantier",
  charge_affaires: "Chargé d'affaires",
  directeur_agence: "Directeur d'agence",
  magasinier: "Magasinier",
  admin: "Administrateur",
};

export const CHILD_ROLE = {
  admin: "directeur_agence",
  directeur_agence: "charge_affaires",
  charge_affaires: "gars_chantier",
};

export const PARENT_ROLE = {
  charge_affaires: "directeur_agence",
  gars_chantier: "charge_affaires",
};
