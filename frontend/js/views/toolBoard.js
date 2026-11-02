// Tableau d'outils de la page d'accueil : chaque outil a sa place peinte, et une place vide signale un prêt.
const TOOLS = {
  hammer:
    "M0 0h96a8 8 0 0 1 8 8v30a8 8 0 0 1-8 8H66v150a9 9 0 0 1-18 0V46H22C8 46 0 34-14 24c8-4 8-20 14-24Z",
  wrench:
    "M-8 0 4 26h20L36 0a36 36 0 0 1 8 62c-5 3-8 7-8 13v134a18 18 0 0 1-36 0V75c0-6-3-10-8-13A36 36 0 0 1-8 0Z",
  drill:
    "M0 0h128a14 14 0 0 1 14 14v8h18v7h46v6h-46v7h-18v8a14 14 0 0 1-14 14H90l14 74h12a10 10 0 0 1 10 10v22a10 10 0 0 1-10 10H34a10 10 0 0 1-10-10v-22a10 10 0 0 1 10-10h18L42 64H0a14 14 0 0 1-14-14V14A14 14 0 0 1 0 0Z",
  pliers:
    "M-9 0h10l7 44 8 20a18 18 0 0 1-3 17l-10 12 12 104a8 8 0 0 1-16 2L-4 112l-3 0-9 87a8 8 0 0 1-16-2l12-104-10-12a18 18 0 0 1-3-17l8-20 7-44h18Z",
  tape:
    "M18 0h82a22 22 0 0 1 22 22v82a18 18 0 0 1-18 18H18A18 18 0 0 1 0 104V18A18 18 0 0 1 18 0Zm40 30a31 31 0 1 0 0 62 31 31 0 0 0 0-62Z",
  level:
    "M10 0h380a10 10 0 0 1 10 10v36a10 10 0 0 1-10 10H10A10 10 0 0 1 0 46V10A10 10 0 0 1 10 0Zm166 16a6 6 0 0 0-6 6v12a6 6 0 0 0 6 6h48a6 6 0 0 0 6-6V22a6 6 0 0 0-6-6h-48Z",
  driver:
    "M-12 0h24a6 6 0 0 1 6 6v70a10 10 0 0 1-10 10H6v96l5 22H-11l5-22V86h-2a10 10 0 0 1-10-10V6a6 6 0 0 1 6-6Z",
};

function peg(x, y) {
  return `<circle class="board-peg" cx="${x}" cy="${y}" r="7"/>`;
}

function tool(path, x, y, scale = 1, classes = "") {
  const size = scale === 1 ? "" : ` scale(${scale})`;
  return `<path class="board-tool ${classes}" fill-rule="evenodd" d="${path}" transform="translate(${x} ${y})${size}"/>`;
}

export const TOOL_BOARD_SVG = `
<svg class="board-art" viewBox="0 0 760 520" role="img" aria-label="Tableau d'outils : marteau, clé, tournevis, pince, mètre et niveau rangés à leur place. La place de la perceuse est vide, l'outil est en prêt.">
  ${peg(92, 40)}${tool(TOOLS.hammer, 56, 54)}
  ${peg(222, 40)}${tool(TOOLS.wrench, 214, 54)}
  ${peg(476, 40)}
  <path class="board-slot" d="${TOOLS.drill}" transform="translate(388 54)"/>
  ${tool(TOOLS.drill, 388, 54, 1, "board-tool-leaving")}
  <g class="board-tag">
    <path class="board-tag-string" d="M476 47c40 10 84 26 124 44"/>
    <g transform="translate(586 84) rotate(5)">
      <path class="board-tag-card" fill-rule="evenodd" d="M16 0h148a6 6 0 0 1 6 6v70a6 6 0 0 1-6 6H16L0 62V20L16 0Zm4 35a6 6 0 1 0 0 12 6 6 0 0 0 0-12Z"/>
      <text class="board-tag-title" x="38" y="35">En prêt</text>
      <text class="board-tag-text" x="38" y="60">Retour vendredi</text>
    </g>
  </g>
  ${peg(324, 40)}${tool(TOOLS.driver, 324, 54)}
  ${peg(640, 270)}${tool(TOOLS.pliers, 640, 284, 0.82)}
  ${peg(90, 296)}${tool(TOOLS.tape, 30, 310, 1.15)}
  ${peg(290, 386)}${peg(490, 386)}${tool(TOOLS.level, 190, 400)}
</svg>`;
