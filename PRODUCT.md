# Product

## Register

Product.

## Platform

Local-first web application packaged for desktop, with development-only engineering tools in the same Svelte SPA.

## Users

The primary user is the project owner, who runs campaigns and needs to recover and defend the architecture for a principal-engineer interview. Technical reviewers are a secondary audience for development-only architecture views.

## Product Purpose

Dungeon Master turns free-form player actions into mechanically resolved, narratively coherent campaign turns. Its architecture map must make the real control flow, data flow, trust boundaries, and source evidence understandable without requiring a codebase tour.

## Positioning

This is an inspectable AI game-master runtime, not a decorative fantasy diagram. The interface should preserve the product's dark-fantasy identity while behaving like a serious engineering tool.

## Brand Personality

Serious, tactile, atmospheric, and precise. Dark wood, ink, parchment, brass, and restrained arcane details are welcome when they support comprehension.

## Anti-references

- Tiny, low-contrast diagrams that require browser zoom.
- Fake depth that obscures topology or causes z-ordering errors.
- Overlapping labels, routes, and nodes.
- Generic corporate dashboard styling.
- Decorative type in controls or dense technical copy.
- Static-document architecture surfaces disconnected from the application.

## Design Principles

- Legibility before atmosphere.
- Make frontend, transport, backend, persistence, and desktop boundaries visible at a glance.
- Use progressive disclosure: overview first, route and source detail on demand.
- Encode real repository behavior only; every architectural claim should lead to source evidence.
- Preserve product identity without making the interface a puzzle.

## Accessibility and Inclusion

Body text and controls must remain readable at normal browser zoom, with WCAG AA contrast, visible keyboard focus, reduced-motion support, and no color-only encoding. The architecture tool must remain usable on a 1280-pixel desktop and a 390-pixel mobile viewport.
