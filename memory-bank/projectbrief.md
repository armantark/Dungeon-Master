# Project Brief

## Project Identity

Working name: AI Game Master / Dungeon Master.

This project is intended to turn an exploratory TTRPG interest into a controlled solo or small-table game experience. The latest direction is a fully fledged personal agentic game system that uses a deterministic solo oracle engine for mechanics and a locked-down LLM narrative layer for prose, without bloated business-MVP abstractions.

## Core Goal

Build a low-friction TTRPG experience that avoids the main blockers discovered in the source note:

- Long scheduled voice calls with strangers are undesirable.
- Public TTRPG spaces may be culturally or politically misaligned.
- Dormant Discord servers are unlikely to produce actual play.
- Pure solo TTRPG play may feel too close to creative writing unless the system provides enough momentum.
- A raw LLM prompt is not reliable enough for long-running rules and inventory state.

The project should therefore provide the feeling of a responsive game master while keeping game state and mechanical outcomes outside the model as strict sources of truth.

## Current Product Direction

The current preferred path is a Streamlit-based application rather than a terminal-only app. Modern Cursor can likely scaffold a complex UI quickly enough that avoiding UI work is not necessary.

The project is not married to OSR. OSR and Scarlet Heroes were originally mentioned because they appeared in a Discord server description and were later used as examples for thinking about high-lethality, rules-aware play. The latest recommendation is to avoid a full OSR rules engine at this stage because strict exploration turns, lethality, and resource tracking add too much friction for the current LLM-assisted architecture.

The preferred mechanical backbone is now a Mythic GME-style deterministic oracle: system-agnostic yes/no resolution, chaos factor, random events, scene checks, threads, and NPC lists implemented in Python. This gives the app enough structure and stakes without requiring a complete RPG rules engine.

## Primary User Needs

- Private, self-directed play without needing to find a Discord group.
- A tone that is apolitical, traditional fantasy, and not driven by modern culture-war themes.
- Deterministic tracking for chaos factor, scenes, threads, NPCs, player notes, and oracle outcomes.
- Clear separation between rules/state logic and creative prose generation.
- A UI engaging enough to make the project feel like a game, not just a prompt box.

## Non-Goals

- Do not build a Discord bot as the first version.
- Do not rely on an LLM to remember canonical state.
- Do not assume OSR is required unless later chosen explicitly.
- Do not implement a full D&D, Pathfinder, or OSR rules engine unless it clearly serves the personal play experience.
- Do not copy proprietary oracle tables verbatim unless the user supplies licensed material or chooses an open alternative.
- Do not start by adapting another repository unless it is clearly simpler than building the base architecture directly.
- Do not change LLM provider or API signature unless explicitly requested.

## Source Material

The raw source note is preserved in `memory-bank/Trying to find a TTRPG community on Discord that i.md`. It records the full exploration from Discord community search to AI game master architecture.
