<script lang="ts">
  import type { ArchitectureNode } from "../../lib/dev-architecture";

  type Point = readonly [number, number];
  interface FaceSet {
    bottom: { north: Point; east: Point; south: Point; west: Point };
    top: { north: Point; east: Point; south: Point; west: Point };
  }

  let {
    node,
    color,
    active,
    selected,
    step,
    onselect,
  }: {
    node: ArchitectureNode;
    color: string;
    active: boolean;
    selected: boolean;
    step?: number;
    onselect: (id: string) => void;
  } = $props();

  const unitX = 15.5;
  const unitY = 7.75;

  function corners(x: number, y: number, width: number, depth: number) {
    return {
      north: [x + unitX * (depth - width), y - unitY * (width + depth)] as Point,
      east: [x + unitX * (width + depth), y + unitY * (width - depth)] as Point,
      south: [x + unitX * (width - depth), y + unitY * (width + depth)] as Point,
      west: [x - unitX * (width + depth), y + unitY * (depth - width)] as Point,
    };
  }

  function prism(
    x: number,
    y: number,
    width: number,
    depth: number,
    height: number,
  ): FaceSet {
    const bottom = corners(x, y, width, depth);
    return {
      bottom,
      top: {
        north: [bottom.north[0], bottom.north[1] - height],
        east: [bottom.east[0], bottom.east[1] - height],
        south: [bottom.south[0], bottom.south[1] - height],
        west: [bottom.west[0], bottom.west[1] - height],
      },
    };
  }

  function points(values: Point[]): string {
    return values.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  }

  function shade(hex: string, amount: number): string {
    const value = Number.parseInt(hex.slice(1), 16);
    const target = amount < 0 ? 0 : 255;
    const mix = Math.abs(amount);
    const channel = (shift: number) => {
      const original = (value >> shift) & 255;
      return Math.round(original + (target - original) * mix);
    };
    return `#${[channel(16), channel(8), channel(0)]
      .map((part) => part.toString(16).padStart(2, "0"))
      .join("")}`;
  }

  const base = $derived(prism(node.x, node.y, node.width, node.depth, node.height));
  const hall = $derived(prism(node.x + 54, node.y + 18, 1.2, 1.1, 34));
  const craneCab = $derived(prism(node.x, node.y, 0.72, 0.72, 56));
  const baseRadiusX = $derived(unitX * (node.width + node.depth));
  const baseRadiusY = $derived(unitY * (node.width + node.depth));

  function select(): void {
    onselect(node.id);
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select();
    }
  }
</script>

<g
  class="building"
  class:building--inactive={!active}
  class:building--selected={selected}
  role="button"
  tabindex="0"
  aria-label={`${node.name}. ${node.responsibility}`}
  data-node-id={node.id}
  onclick={select}
  onkeydown={handleKeydown}
>
  <ellipse
    class="shadow"
    cx={node.x}
    cy={node.y + 5}
    rx={baseRadiusX * 0.9}
    ry={baseRadiusY * 0.78}
  />

  {#if node.kind === "cistern"}
    <path
      d={`M ${node.x - baseRadiusX * 0.76} ${node.y}
          L ${node.x - baseRadiusX * 0.76} ${node.y - node.height}
          A ${baseRadiusX * 0.76} ${baseRadiusY * 0.76} 0 0 0 ${node.x + baseRadiusX * 0.76} ${node.y - node.height}
          L ${node.x + baseRadiusX * 0.76} ${node.y}
          A ${baseRadiusX * 0.76} ${baseRadiusY * 0.76} 0 0 1 ${node.x - baseRadiusX * 0.76} ${node.y} Z`}
      fill={shade(color, -0.38)}
      stroke={shade(color, -0.62)}
    />
    <ellipse
      cx={node.x}
      cy={node.y - node.height}
      rx={baseRadiusX * 0.76}
      ry={baseRadiusY * 0.76}
      fill={shade(color, 0.18)}
      stroke={shade(color, 0.38)}
    />
    <ellipse
      cx={node.x}
      cy={node.y - node.height}
      rx={baseRadiusX * 0.35}
      ry={baseRadiusY * 0.35}
      fill={shade(color, -0.08)}
      stroke={shade(color, 0.38)}
    />
    <path class="detail" d={`M ${node.x - baseRadiusX * 0.72} ${node.y - 18} A ${baseRadiusX * 0.72} ${baseRadiusY * 0.72} 0 0 0 ${node.x + baseRadiusX * 0.72} ${node.y - 18}`} />
  {:else}
    <polygon
      points={points([base.bottom.west, base.bottom.south, base.top.south, base.top.west])}
      fill={shade(color, -0.22)}
      stroke={shade(color, -0.56)}
    />
    <polygon
      points={points([base.bottom.south, base.bottom.east, base.top.east, base.top.south])}
      fill={shade(color, -0.43)}
      stroke={shade(color, -0.62)}
    />
    <polygon
      points={points([base.top.north, base.top.east, base.top.south, base.top.west])}
      fill={shade(color, 0.17)}
      stroke={shade(color, 0.36)}
    />

    {#if node.kind === "gatehouse"}
      <path
        class="void"
        d={`M ${node.x - 13} ${node.y - 3} L ${node.x - 13} ${node.y - 29}
            Q ${node.x} ${node.y - 45} ${node.x + 13} ${node.y - 29}
            L ${node.x + 13} ${node.y - 3} Z`}
      />
      <line class="gold-detail" x1={node.x - 30} y1={node.y - 47} x2={node.x + 30} y2={node.y - 47} />
    {:else if node.kind === "relay"}
      <line class="mast" x1={node.x} y1={node.y - node.height - 2} x2={node.x} y2={node.y - node.height - 35} />
      <circle class="signal" cx={node.x} cy={node.y - node.height - 38} r="4" />
      <path class="signal-wave" d={`M ${node.x - 16} ${node.y - node.height - 29} Q ${node.x} ${node.y - node.height - 45} ${node.x + 16} ${node.y - node.height - 29}`} />
    {:else if node.kind === "depot"}
      {#each [0.24, 0.5, 0.76] as fraction}
        <line
          class="roof-rib"
          x1={base.top.west[0] + (base.top.north[0] - base.top.west[0]) * fraction}
          y1={base.top.west[1] + (base.top.north[1] - base.top.west[1]) * fraction}
          x2={base.top.south[0] + (base.top.east[0] - base.top.south[0]) * fraction}
          y2={base.top.south[1] + (base.top.east[1] - base.top.south[1]) * fraction}
        />
      {/each}
      <rect class="door" x={node.x + 29} y={node.y - 28} width="22" height="24" />
    {:else if node.kind === "foundry"}
      {#each [-20, 18] as offset, index}
        <rect
          x={node.x + offset - 6}
          y={node.y - node.height - 35 - index * 11}
          width="12"
          height={35 + index * 11}
          fill={shade(color, -0.28)}
          stroke={shade(color, -0.58)}
        />
        <ellipse cx={node.x + offset} cy={node.y - node.height - 35 - index * 11} rx="6" ry="3" fill={shade(color, 0.24)} />
      {/each}
      <rect class="furnace" x={node.x + 18} y={node.y - 34} width="30" height="24" />
    {:else if node.kind === "observatory"}
      <path
        d={`M ${node.x - 34} ${node.y - node.height}
            A 34 25 0 0 1 ${node.x + 34} ${node.y - node.height}
            A 34 9 0 0 1 ${node.x - 34} ${node.y - node.height} Z`}
        fill={shade(color, 0.14)}
        stroke={shade(color, 0.44)}
      />
      <line class="mast" x1={node.x} y1={node.y - node.height - 12} x2={node.x + 22} y2={node.y - node.height - 42} />
    {:else if node.kind === "tower"}
      <polygon
        points={points([
          base.top.west,
          base.top.south,
          [node.x, base.top.north[1] - 36],
        ])}
        fill={shade(color, -0.08)}
        stroke={shade(color, -0.48)}
      />
      <polygon
        points={points([
          base.top.south,
          base.top.east,
          [node.x, base.top.north[1] - 36],
        ])}
        fill={shade(color, -0.34)}
        stroke={shade(color, -0.52)}
      />
      <circle class="signal" cx={node.x} cy={base.top.north[1] - 41} r="4" />
      <polygon points={points([hall.bottom.west, hall.bottom.south, hall.top.south, hall.top.west])} fill={shade(color, -0.26)} stroke={shade(color, -0.56)} />
      <polygon points={points([hall.bottom.south, hall.bottom.east, hall.top.east, hall.top.south])} fill={shade(color, -0.47)} stroke={shade(color, -0.64)} />
      <polygon points={points([hall.top.north, hall.top.east, hall.top.south, hall.top.west])} fill={shade(color, 0.09)} stroke={shade(color, 0.34)} />
      <line class="connector" x1={base.bottom.east[0] - 3} y1={base.bottom.east[1] - 16} x2={hall.bottom.west[0] + 5} y2={hall.bottom.west[1] - 16} />
    {:else if node.kind === "theater"}
      <polygon class="pediment" points={`${node.x - 38},${node.y - node.height} ${node.x},${node.y - node.height - 25} ${node.x + 38},${node.y - node.height}`} />
      {#each [-26, -9, 9, 26] as offset}
        <line class="column-line" x1={node.x + offset} y1={node.y - node.height + 5} x2={node.x + offset} y2={node.y - 5} />
      {/each}
    {:else if node.kind === "loom" || node.kind === "works"}
      {#each [-25, 0, 25] as offset}
        <path class="saw" d={`M ${node.x + offset - 13} ${node.y - node.height} L ${node.x + offset} ${node.y - node.height - 15} L ${node.x + offset + 13} ${node.y - node.height}`} />
      {/each}
      <rect class="door" x={node.x + 14} y={node.y - 25} width="22" height="20" />
    {:else if node.kind === "vault"}
      <rect class="vault-door" x={node.x + 5} y={node.y - 39} width="34" height="32" rx="17" />
      {#each [-30, -10, 10, 30] as offset}
        <line class="roof-rib" x1={node.x + offset - 10} y1={node.y - node.height - 4} x2={node.x + offset + 10} y2={node.y - node.height + 6} />
      {/each}
    {:else if node.kind === "library"}
      {#each [-22, -7, 8, 23] as offset}
        <line class="shelf-line" x1={node.x + offset} y1={node.y - node.height + 4} x2={node.x + offset + 22} y2={node.y - 8} />
      {/each}
      <polygon class="clerestory" points={`${node.x - 31},${node.y - node.height} ${node.x},${node.y - node.height - 18} ${node.x + 31},${node.y - node.height}`} />
    {:else if node.kind === "homes"}
      <polygon class="roof" points={`${node.x - 42},${node.y - node.height} ${node.x - 15},${node.y - node.height - 25} ${node.x + 10},${node.y - node.height}`} />
      <polygon class="roof" points={`${node.x + 3},${node.y - node.height} ${node.x + 27},${node.y - node.height - 22} ${node.x + 49},${node.y - node.height}`} />
      <rect class="window" x={node.x + 14} y={node.y - 23} width="10" height="12" />
    {:else if node.kind === "shell"}
      {#each [-38, -13, 13, 38] as offset}
        <rect x={node.x + offset - 6} y={node.y - node.height - 11} width="12" height="11" fill={shade(color, 0.12)} stroke={shade(color, -0.5)} />
      {/each}
      <path class="void" d={`M ${node.x - 11} ${node.y - 2} L ${node.x - 11} ${node.y - 27} Q ${node.x} ${node.y - 38} ${node.x + 11} ${node.y - 27} L ${node.x + 11} ${node.y - 2} Z`} />
    {:else if node.kind === "crane"}
      <polygon points={points([craneCab.bottom.west, craneCab.bottom.south, craneCab.top.south, craneCab.top.west])} fill={shade(color, -0.24)} stroke={shade(color, -0.58)} />
      <polygon points={points([craneCab.bottom.south, craneCab.bottom.east, craneCab.top.east, craneCab.top.south])} fill={shade(color, -0.45)} stroke={shade(color, -0.64)} />
      <polygon points={points([craneCab.top.north, craneCab.top.east, craneCab.top.south, craneCab.top.west])} fill={shade(color, 0.15)} stroke={shade(color, 0.35)} />
      <line class="boom" x1={node.x} y1={node.y - node.height - 40} x2={node.x + 74} y2={node.y - node.height - 18} />
      <line class="boom-thin" x1={node.x + 68} y1={node.y - node.height - 20} x2={node.x + 68} y2={node.y - node.height + 25} />
      <path class="hook" d={`M ${node.x + 63} ${node.y - node.height + 25} q 5 9 10 0`} />
    {/if}
  {/if}

  <polygon
    class="selection-ring"
    points={points([
      base.bottom.north,
      base.bottom.east,
      base.bottom.south,
      base.bottom.west,
    ])}
  />

  {#if step !== undefined}
    <g class="step-chip" aria-hidden="true">
      <circle cx={node.x} cy={node.y + baseRadiusY + 8} r="11" />
      <text x={node.x} y={node.y + baseRadiusY + 12}>{step}</text>
    </g>
  {/if}
</g>

<style>
  .building {
    cursor: pointer;
    transition: opacity 170ms ease, filter 170ms ease;
  }
  .building--inactive {
    opacity: 1;
    filter: saturate(0.28) brightness(0.58);
  }
  .building:hover,
  .building:focus-visible,
  .building--selected {
    opacity: 1;
    filter: drop-shadow(0 0 8px color-mix(in srgb, #d9b15a 62%, transparent));
    outline: none;
  }
  polygon,
  path,
  ellipse,
  rect,
  line { vector-effect: non-scaling-stroke; stroke-width: 1.15; }
  .shadow { fill: rgba(0, 0, 0, 0.52); stroke: none; }
  .selection-ring { fill: none; stroke: transparent; stroke-width: 2.5; }
  .building--selected .selection-ring { stroke: #e0b45c; stroke-dasharray: 5 4; }
  .detail,
  .signal-wave { fill: none; stroke: rgba(228, 219, 194, 0.45); }
  .void { fill: #100d09; stroke: #4b3827; }
  .gold-detail,
  .connector { stroke: #d9b15a; stroke-width: 2; }
  .mast { stroke: #18140f; stroke-width: 4; }
  .signal { fill: #e2b44d; stroke: #6e4d12; }
  .roof-rib,
  .shelf-line { stroke: rgba(12, 10, 8, 0.43); }
  .door { fill: #2a1b14; stroke: #bd6a3f; }
  .furnace { fill: #da713d; stroke: #582117; }
  .pediment,
  .roof,
  .clerestory { fill: rgba(235, 213, 166, 0.18); stroke: rgba(235, 213, 166, 0.48); }
  .column-line { stroke: rgba(18, 12, 9, 0.55); stroke-width: 3; }
  .saw { fill: rgba(238, 221, 181, 0.14); stroke: rgba(238, 221, 181, 0.4); }
  .vault-door { fill: #18130d; stroke: #d0a44d; stroke-width: 2; }
  .window { fill: #f2c65a; stroke: #72531c; }
  .boom { stroke: #17120d; stroke-width: 6; }
  .boom-thin,
  .hook { fill: none; stroke: #b98d38; stroke-width: 2; }
  .step-chip circle { fill: #3b2d12; stroke: #d9b15a; stroke-width: 1.4; }
  .step-chip text {
    fill: #f1d584;
    font: 700 11px/1 var(--font-pixel);
    text-anchor: middle;
  }
  @media (prefers-reduced-motion: reduce) {
    .building { transition: none; }
  }
</style>
