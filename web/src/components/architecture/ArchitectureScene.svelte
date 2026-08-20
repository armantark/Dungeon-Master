<script lang="ts">
  import { onMount } from "svelte";
  import * as THREE from "three";
  import {
    ARCHITECTURE_NODES,
    ROLE_META,
    nodeById,
    routeSegmentAt,
    type ArchitectureNode,
    type ArchitecturePath,
  } from "../../lib/dev-architecture";

  interface LabelPoint {
    left: number;
    top: number;
  }

  interface Territory {
    id: string;
    color: string;
    center: readonly [number, number];
    size: readonly [number, number];
  }

  let {
    activePath,
    selectedNodeId,
    traceIndex,
    onSelect,
  }: {
    activePath: ArchitecturePath;
    selectedNodeId: string;
    traceIndex: number;
    onSelect: (id: string) => void;
  } = $props();

  const WORLD_POSITIONS: Record<string, readonly [number, number]> = {
    composer: [-8, 3],
    relay: [-8, 0],
    homes: [-8, -3],
    depot: [-3, 3],
    foundry: [1, 3],
    router: [5, 3],
    memory: [1, 0],
    oracle: [5, 0],
    narrative: [1, -3],
    loom: [5, -3],
    vault: [-5, -6],
    library: [-1.25, -6],
    shell: [2.5, -6],
    sidecar: [6, -6],
    crane: [9, -6],
  };

  const TERRITORIES: Territory[] = [
    { id: "frontend", color: "#3f8b91", center: [-8, 0], size: [4.2, 9.2] },
    { id: "transport", color: "#b88a31", center: [-3, 3], size: [3.2, 3.2] },
    { id: "backend", color: "#68788f", center: [3, 0], size: [8.2, 9.2] },
    { id: "persistence", color: "#a88434", center: [-3.2, -6], size: [7.8, 3.2] },
    { id: "desktop", color: "#557c5e", center: [5.8, -6], size: [9.2, 3.2] },
  ];

  let canvas: HTMLCanvasElement;
  let frame: HTMLDivElement;
  let labelPoints = $state<Record<string, LabelPoint>>({});
  let hoveredNodeId = $state<string | null>(null);

  const activeIds = $derived(new Set(activePath.steps.map((step) => step.node)));
  const currentStep = $derived(
    traceIndex >= 0 ? activePath.steps[traceIndex] : undefined,
  );
  const currentSegment = $derived(routeSegmentAt(activePath, traceIndex));
  const previousStep = $derived(currentSegment?.from);
  const currentNode = $derived(currentStep ? nodeById(currentStep.node) : undefined);
  const previousNode = $derived(previousStep ? nodeById(previousStep.node) : undefined);

  function stepNumber(nodeId: string): number | undefined {
    const index = activePath.steps.findIndex((step) => step.node === nodeId);
    return index >= 0 ? index + 1 : undefined;
  }

  function shade(hex: string, lightness: number): THREE.Color {
    return new THREE.Color(hex).offsetHSL(0, 0, lightness);
  }

  function buildingHeight(node: ArchitectureNode): number {
    return Math.max(1.15, Math.min(3.1, 0.65 + node.height / 48));
  }

  function makeMaterial(color: string, lightness = 0): THREE.MeshStandardMaterial {
    return new THREE.MeshStandardMaterial({
      color: shade(color, lightness),
      roughness: 0.72,
      metalness: 0.08,
    });
  }

  function addMesh(
    group: THREE.Group,
    geometry: THREE.BufferGeometry,
    material: THREE.Material,
    position: readonly [number, number, number],
    nodeId: string,
  ): THREE.Mesh {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(...position);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.nodeId = nodeId;
    group.add(mesh);
    return mesh;
  }

  function addBox(
    group: THREE.Group,
    node: ArchitectureNode,
    size: readonly [number, number, number],
    position: readonly [number, number, number],
    lightness = 0,
  ): THREE.Mesh {
    return addMesh(
      group,
      new THREE.BoxGeometry(...size),
      makeMaterial(ROLE_META[node.role].color, lightness),
      position,
      node.id,
    );
  }

  function addCylinder(
    group: THREE.Group,
    node: ArchitectureNode,
    radius: number,
    height: number,
    position: readonly [number, number, number],
    lightness = 0,
    segments = 20,
  ): THREE.Mesh {
    return addMesh(
      group,
      new THREE.CylinderGeometry(radius, radius, height, segments),
      makeMaterial(ROLE_META[node.role].color, lightness),
      position,
      node.id,
    );
  }

  function addRoof(
    group: THREE.Group,
    node: ArchitectureNode,
    radius: number,
    height: number,
    position: readonly [number, number, number],
    segments = 4,
  ): THREE.Mesh {
    const roof = addMesh(
      group,
      new THREE.ConeGeometry(radius, height, segments),
      makeMaterial(ROLE_META[node.role].color, 0.18),
      position,
      node.id,
    );
    roof.rotation.y = Math.PI / 4;
    return roof;
  }

  function createBuilding(node: ArchitectureNode): THREE.Group {
    const group = new THREE.Group();
    const height = buildingHeight(node);
    const width = 1.15 + node.width * 0.34;
    const depth = 1.05 + node.depth * 0.32;
    const bodyY = height / 2;

    switch (node.kind) {
      case "gatehouse":
        addBox(group, node, [width * 0.38, height * 1.15, depth], [-width * 0.36, height * 0.575, 0], -0.04);
        addBox(group, node, [width * 0.38, height * 1.15, depth], [width * 0.36, height * 0.575, 0], -0.04);
        addBox(group, node, [width * 0.55, height * 0.3, depth * 0.72], [0, height * 0.95, 0], 0.08);
        addRoof(group, node, width * 0.32, height * 0.38, [-width * 0.36, height * 1.33, 0]);
        addRoof(group, node, width * 0.32, height * 0.38, [width * 0.36, height * 1.33, 0]);
        break;
      case "relay":
        addBox(group, node, [width, height, depth], [0, bodyY, 0]);
        addCylinder(group, node, 0.07, height * 1.1, [0, height * 1.55, 0], 0.22, 10);
        addMesh(group, new THREE.SphereGeometry(0.16, 12, 8), makeMaterial("#d8ae4d", 0.12), [0, height * 2.12, 0], node.id);
        break;
      case "depot":
        addBox(group, node, [width * 1.35, height * 0.75, depth], [0, height * 0.375, 0]);
        addRoof(group, node, width * 0.9, height * 0.52, [0, height * 1.01, 0]);
        break;
      case "foundry":
        addBox(group, node, [width * 1.1, height * 0.82, depth], [0, height * 0.41, 0], -0.06);
        addBox(group, node, [width * 0.4, height * 0.45, depth * 0.62], [width * 0.52, height * 0.225, 0], 0.1);
        addCylinder(group, node, 0.16, height * 1.15, [-width * 0.25, height * 1.15, -depth * 0.2], -0.18, 12);
        addCylinder(group, node, 0.13, height * 1.45, [width * 0.18, height * 1.3, -depth * 0.2], -0.22, 12);
        break;
      case "cistern":
        addCylinder(group, node, width * 0.46, height * 0.72, [0, height * 0.36, 0], -0.08, 28);
        addMesh(group, new THREE.TorusGeometry(width * 0.3, 0.08, 8, 24), makeMaterial(ROLE_META[node.role].color, 0.24), [0, height * 0.74, 0], node.id).rotation.x = Math.PI / 2;
        break;
      case "observatory": {
        addCylinder(group, node, width * 0.43, height * 0.78, [0, height * 0.39, 0], -0.05, 24);
        const dome = addMesh(
          group,
          new THREE.SphereGeometry(width * 0.44, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2),
          makeMaterial(ROLE_META[node.role].color, 0.2),
          [0, height * 0.78, 0],
          node.id,
        );
        dome.scale.y = 0.72;
        break;
      }
      case "tower":
        addCylinder(group, node, width * 0.36, height * 1.28, [0, height * 0.64, 0], -0.08, 8);
        addRoof(group, node, width * 0.47, height * 0.62, [0, height * 1.59, 0], 8);
        addBox(group, node, [width * 0.76, height * 0.42, depth * 0.7], [width * 0.5, height * 0.21, depth * 0.25], 0.08);
        break;
      case "theater":
        addBox(group, node, [width * 1.25, height * 0.72, depth], [0, height * 0.36, 0], -0.08);
        for (const x of [-0.45, -0.15, 0.15, 0.45]) {
          addCylinder(group, node, 0.075, height * 0.72, [x * width, height * 0.36, depth * 0.55], 0.2, 10);
        }
        addRoof(group, node, width * 0.82, height * 0.5, [0, height * 0.95, 0]);
        break;
      case "loom":
      case "works":
        addBox(group, node, [width * 1.15, height * 0.72, depth], [0, height * 0.36, 0], -0.08);
        for (const x of [-0.36, 0, 0.36]) {
          addRoof(group, node, width * 0.28, height * 0.42, [x * width, height * 0.88, 0]);
        }
        break;
      case "vault": {
        addBox(group, node, [width * 1.15, height * 0.86, depth * 1.08], [0, height * 0.43, 0], -0.14);
        const door = addMesh(group, new THREE.TorusGeometry(0.36, 0.09, 10, 24, Math.PI), makeMaterial("#d1a84a", -0.02), [0, height * 0.38, depth * 0.55], node.id);
        door.rotation.z = Math.PI / 2;
        break;
      }
      case "library":
        addBox(group, node, [width * 1.35, height * 0.78, depth], [0, height * 0.39, 0]);
        addRoof(group, node, width * 0.88, height * 0.48, [0, height * 1.02, 0]);
        for (const x of [-0.42, -0.14, 0.14, 0.42]) {
          addBox(group, node, [0.07, height * 0.48, 0.08], [x * width, height * 0.28, depth * 0.53], 0.24);
        }
        break;
      case "homes":
        for (const [x, z, scale] of [[-0.48, 0.22, 0.72], [0.38, 0.2, 0.64], [-0.05, -0.38, 0.58]] as const) {
          addBox(group, node, [width * scale, height * 0.55 * scale, depth * 0.65 * scale], [x * width, height * 0.275 * scale, z * depth], -0.04);
          addRoof(group, node, width * 0.46 * scale, height * 0.36 * scale, [x * width, height * 0.72 * scale, z * depth]);
        }
        break;
      case "shell":
        addBox(group, node, [width * 1.18, height * 0.72, depth], [0, height * 0.36, 0], -0.08);
        for (const x of [-0.47, 0.47]) {
          for (const z of [-0.4, 0.4]) {
            addBox(group, node, [0.26, height * 0.42, 0.26], [x * width, height * 0.93, z * depth], 0.12);
          }
        }
        break;
      case "crane": {
        addBox(group, node, [0.42, height * 1.55, 0.42], [0, height * 0.775, 0], -0.12);
        const boom = addBox(group, node, [width * 1.8, 0.18, 0.18], [width * 0.52, height * 1.55, 0], 0.16);
        boom.rotation.z = -0.16;
        addCylinder(group, node, 0.05, height * 0.72, [width * 1.32, height * 1.1, 0], 0.22, 8);
        break;
      }
      default:
        addBox(group, node, [width, height, depth], [0, bodyY, 0]);
        addRoof(group, node, width * 0.62, height * 0.42, [0, height * 1.18, 0]);
    }

    const [x, z] = WORLD_POSITIONS[node.id] ?? [0, 0];
    group.position.set(x, 0, z);
    group.userData.nodeId = node.id;
    group.userData.anchorY = height * (node.kind === "crane" ? 1.85 : 1.5);
    return group;
  }

  onMount(() => {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#090806");
    scene.fog = new THREE.Fog("#090806", 24, 48);

    const camera = new THREE.OrthographicCamera(-13.5, 13.5, 9, -9, 0.1, 100);
    camera.position.set(18, 18, -22);
    camera.lookAt(0, 0, -1.5);

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, depth: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;

    scene.add(new THREE.HemisphereLight("#d7c9a7", "#18100b", 2.1));
    const keyLight = new THREE.DirectionalLight("#ffe1a0", 3.3);
    keyLight.position.set(-8, 16, 10);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.set(2048, 2048);
    keyLight.shadow.camera.left = -18;
    keyLight.shadow.camera.right = 18;
    keyLight.shadow.camera.top = 18;
    keyLight.shadow.camera.bottom = -18;
    scene.add(keyLight);

    const grid = new THREE.GridHelper(32, 32, "#483719", "#201a12");
    grid.position.y = -0.34;
    scene.add(grid);

    for (const territory of TERRITORIES) {
      const plate = new THREE.Mesh(
        new THREE.BoxGeometry(territory.size[0], 0.3, territory.size[1]),
        new THREE.MeshStandardMaterial({
          color: shade(territory.color, -0.24),
          emissive: shade(territory.color, -0.42),
          emissiveIntensity: 0.3,
          roughness: 0.95,
          metalness: 0,
        }),
      );
      plate.position.set(territory.center[0], -0.15, territory.center[1]);
      plate.receiveShadow = true;
      scene.add(plate);
    }

    const buildingGroups = new Map<string, THREE.Group>();
    const buildingAnchors = new Map<string, THREE.Vector3>();
    for (const node of ARCHITECTURE_NODES) {
      const building = createBuilding(node);
      buildingGroups.set(node.id, building);
      buildingAnchors.set(
        node.id,
        new THREE.Vector3(
          building.position.x,
          building.userData.anchorY as number,
          building.position.z,
        ),
      );
      scene.add(building);
    }

    const routeGroup = new THREE.Group();
    scene.add(routeGroup);

    function disposeObject(object: THREE.Object3D): void {
      object.traverse((child) => {
        if (!(child instanceof THREE.Mesh || child instanceof THREE.Line)) return;
        child.geometry.dispose();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        for (const material of materials) material.dispose();
      });
    }

    function clearRoute(): void {
      for (const child of [...routeGroup.children]) {
        routeGroup.remove(child);
        disposeObject(child);
      }
    }

    function drawRoute(): void {
      clearRoute();
      if (!previousStep || !currentStep) return;
      const startPosition = WORLD_POSITIONS[previousStep.node];
      const endPosition = WORLD_POSITIONS[currentStep.node];
      if (!startPosition || !endPosition) return;

      const start = new THREE.Vector3(startPosition[0], 1.05, startPosition[1]);
      const end = new THREE.Vector3(endPosition[0], 1.05, endPosition[1]);
      const distance = start.distanceTo(end);
      const midpoint = start.clone().lerp(end, 0.5);
      midpoint.y = 2.2 + Math.min(2.2, distance * 0.18);
      const curve = new THREE.CatmullRomCurve3([start, midpoint, end]);
      const route = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 40, 0.075, 8, false),
        new THREE.MeshStandardMaterial({
          color: "#f1bd47",
          emissive: "#9f6415",
          emissiveIntensity: 1.4,
          roughness: 0.38,
          depthTest: true,
          depthWrite: false,
        }),
      );
      route.renderOrder = 4;
      routeGroup.add(route);

      const tangent = curve.getTangent(1).normalize();
      const arrow = new THREE.Mesh(
        new THREE.ConeGeometry(0.22, 0.58, 10),
        new THREE.MeshStandardMaterial({ color: "#ffd36a", emissive: "#a86e19", emissiveIntensity: 1.2 }),
      );
      arrow.position.copy(end);
      arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tangent);
      routeGroup.add(arrow);
    }

    function updateBuildingState(): void {
      for (const node of ARCHITECTURE_NODES) {
        const group = buildingGroups.get(node.id);
        if (!group) continue;
        const active = activeIds.has(node.id);
        const selected = selectedNodeId === node.id;
        group.traverse((child) => {
          if (!(child instanceof THREE.Mesh)) return;
          const materials = Array.isArray(child.material) ? child.material : [child.material];
          for (const material of materials) {
            if (!(material instanceof THREE.MeshStandardMaterial)) continue;
            material.transparent = !active;
            material.opacity = active ? 1 : 0.36;
            material.emissive.set(selected ? "#8c5a16" : "#000000");
            material.emissiveIntensity = selected ? 0.72 : 0;
            material.depthWrite = active;
          }
        });
      }
    }

    function projectPoint(point: THREE.Vector3): LabelPoint {
      const projected = point.clone().project(camera);
      return {
        left: (projected.x * 0.5 + 0.5) * 100,
        top: (-projected.y * 0.5 + 0.5) * 100,
      };
    }

    function updateProjectedLabels(): void {
      labelPoints = Object.fromEntries(
        [...buildingAnchors].map(([id, point]) => [id, projectPoint(point)]),
      );
    }

    function resize(): void {
      const width = Math.max(1, frame.clientWidth);
      const height = Math.max(1, frame.clientHeight);
      const aspect = width / height;
      const halfWidth = 13.5;
      const halfHeight = halfWidth / aspect;
      camera.left = -halfWidth;
      camera.right = halfWidth;
      camera.top = halfHeight;
      camera.bottom = -halfHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      updateProjectedLabels();
      renderer.render(scene, camera);
    }

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    function nodeAtPointer(event: PointerEvent): string | null {
      const rect = canvas.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const intersections = raycaster.intersectObjects([...buildingGroups.values()], true);
      for (const intersection of intersections) {
        let object: THREE.Object3D | null = intersection.object;
        while (object) {
          if (typeof object.userData.nodeId === "string") return object.userData.nodeId;
          object = object.parent;
        }
      }
      return null;
    }

    function handlePointerMove(event: PointerEvent): void {
      hoveredNodeId = nodeAtPointer(event);
      canvas.style.cursor = hoveredNodeId ? "pointer" : "default";
    }

    function handlePointerLeave(): void {
      hoveredNodeId = null;
      canvas.style.cursor = "default";
    }

    function handlePointerDown(event: PointerEvent): void {
      const nodeId = nodeAtPointer(event);
      if (nodeId) onSelect(nodeId);
    }

    canvas.addEventListener("pointermove", handlePointerMove);
    canvas.addEventListener("pointerleave", handlePointerLeave);
    canvas.addEventListener("pointerdown", handlePointerDown);

    const observer = new ResizeObserver(resize);
    observer.observe(frame);

    const updateScene = (): void => {
      updateBuildingState();
      drawRoute();
      updateProjectedLabels();
      renderer.render(scene, camera);
    };

    resize();
    updateScene();

    const stopEffect = $effect.root(() => {
      $effect(() => {
        activePath;
        selectedNodeId;
        traceIndex;
        updateScene();
      });
    });

    return () => {
      stopEffect();
      observer.disconnect();
      canvas.removeEventListener("pointermove", handlePointerMove);
      canvas.removeEventListener("pointerleave", handlePointerLeave);
      canvas.removeEventListener("pointerdown", handlePointerDown);
      clearRoute();
      disposeObject(scene);
      renderer.dispose();
    };
  });
</script>

<div class="scene-frame" bind:this={frame}>
  <canvas bind:this={canvas} aria-hidden="true"></canvas>

  <div class="building-labels" aria-label="Architecture infrastructure">
    {#each ARCHITECTURE_NODES as node}
      {@const point = labelPoints[node.id]}
      {@const step = stepNumber(node.id)}
      {#if point}
        <button
          type="button"
          class:active={activeIds.has(node.id)}
          class:selected={selectedNodeId === node.id}
          class:hovered={hoveredNodeId === node.id}
          aria-pressed={selectedNodeId === node.id}
          aria-label={`${step ? `Step ${step}. ` : ""}${node.name}. ${node.responsibility}`}
          style={`--left:${point.left}%;--top:${point.top}%;--role:${ROLE_META[node.role].color}`}
          onclick={() => onSelect(node.id)}
        >
          {#if step}<span class="building-label__step">{step}</span>{/if}
          <span class="building-label__name">{node.name}</span>
        </button>
      {/if}
    {/each}
  </div>

  {#if currentNode}
    <div class="route-readout" aria-live="polite">
      <span class="route-readout__step">Step {traceIndex + 1}</span>
      {#if previousNode}
        <strong>{previousNode.name} → {currentNode.name}</strong>
      {:else}
        <strong>{currentNode.name}</strong>
      {/if}
      {#if currentStep?.payload}<code>{currentStep.payload}</code>{/if}
    </div>
  {/if}
</div>

<style>
  .scene-frame {
    position: relative;
    height: 660px;
    overflow: hidden;
    background: #090806;
    border-bottom: var(--rule-hair);
    isolation: isolate;
  }

  canvas {
    display: block;
    width: 100%;
    height: 100%;
  }

  .building-labels button {
    position: absolute;
    left: var(--left);
    top: var(--top);
    transform: translate(-50%, -100%);
  }

  .building-labels button {
    display: none;
    align-items: center;
    gap: 0.35rem;
    max-width: 12rem;
    padding: 0.3rem 0.45rem;
    color: #efe7d2;
    background: rgba(13, 11, 8, 0.9);
    border: 1px solid color-mix(in srgb, var(--role) 78%, #0b0907);
    box-shadow: 0 3px 6px rgba(0, 0, 0, 0.58);
    font: 600 14px/1.15 ui-sans-serif, system-ui, sans-serif;
    text-align: left;
    text-transform: none;
    white-space: normal;
    cursor: pointer;
    transition: opacity 120ms ease, border-color 120ms ease, background 120ms ease;
  }

  .building-labels button.active,
  .building-labels button.selected,
  .building-labels button.hovered { display: inline-flex; }
  .building-labels button.active:not(.selected):not(.hovered) {
    padding: 0;
    background: transparent;
    border: 0;
    box-shadow: none;
  }
  .building-labels button.active:not(.selected):not(.hovered) .building-label__name { display: none; }
  .building-labels button:hover,
  .building-labels button.hovered,
  .building-labels button.selected {
    z-index: 3;
    opacity: 1;
    color: #fff2be;
    background: #241a0d;
    border-color: var(--gold-bright);
  }

  .building-label__step {
    display: grid;
    place-items: center;
    flex: 0 0 auto;
    width: 1.45rem;
    height: 1.45rem;
    border-radius: 50%;
    color: #ffe39b;
    background: #3b2d12;
    border: 1px solid var(--gold-bright);
    font-family: var(--font-pixel);
  }

  .route-readout {
    position: absolute;
    left: 0.75rem;
    z-index: 4;
    max-width: calc(100% - 1.5rem);
    background: rgba(9, 8, 6, 0.92);
    border: 1px solid #665126;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.65);
  }

  .route-readout {
    bottom: 0.75rem;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem 0.7rem;
    padding: 0.55rem 0.7rem;
    color: #f1e8d1;
    font: 16px/1.3 ui-sans-serif, system-ui, sans-serif;
  }

  .route-readout__step { color: #efbd4b; font-family: var(--font-pixel); }
  .route-readout code { color: #ffe08a; font-size: 0.95rem; }

  @media (max-width: 900px) {
    .scene-frame { height: 500px; }
    .building-labels button:not(.selected) .building-label__name { display: none; }
    .building-labels button:not(.selected) {
      padding: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .building-labels button { transition: none; }
  }
</style>
