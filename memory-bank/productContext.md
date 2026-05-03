# Product Context

## Why This Exists

The source discussion began as a search for a TTRPG community that would be socially comfortable, culturally aligned, and actually active. The exploration found that online groups introduce several frictions: dead servers, uncertain fit with strangers, long calls, theological or cultural mismatch, and the difficulty of finding a truly apolitical table.

The product direction emerged from that friction. Instead of depending on a public community, the user wants a controlled application that can provide the creative responsiveness of tabletop play while removing scheduling, group discovery, and social-filtering problems.

## User Profile and Constraints

The source note repeatedly emphasizes:

- The user is a software engineer and is comfortable with agentic systems.
- The user prefers traditional Christian or at least genuinely apolitical environments.
- The user is hesitant about recurring four-hour voice calls with strangers.
- ADHD-PI and executive-function friction make high-prep hobbies risky.
- Novelty, visual polish, and immediate feedback may help maintain momentum.
- The user is willing to use LLMs, Cursor, and custom harnesses to make the experience work.

These constraints point toward an app that starts fast, automates setup, and makes state visible, while still being treated as a serious personal enjoyment project rather than a disposable MVP.

## Experience Goals

The application should feel like sitting down to play, not like maintaining an engineering demo. The user should be able to open the app, see the current scene and world state, ask oracle questions, generate events, check scenes, submit actions, and receive coherent prose grounded in deterministic outcomes.

The ideal loop:

1. User enters an action.
2. The system classifies whether the action needs oracle resolution, random event generation, scene checking, or narrative continuation.
3. Dice, chaos factor, scene checks, threads, and NPC references are handled outside freeform prose.
4. State updates are validated and persisted.
5. The narrative layer presents the outcome in the requested tone without changing canonical state.

## Tone and Content Preferences

The desired tone is gritty, traditional, dark fantasy, and apolitical, with inspiration from oppressive dark fantasy such as `Berserk` and `Fear & Hunger`: bleak medieval decay, body horror, famine, occult pressure, and real danger. The app should avoid injecting modern ideological framing into the fiction. This is a product preference about tone and setting control, not a reason to copy hostile or inflammatory wording from the raw note into generated product artifacts.

## Alternatives Considered

- Join Saga Society or similar traditional Christian communities: culturally promising but links may be broken or communities may be inactive.
- Play-by-post: lowers social pressure but often loses momentum.
- Local game stores: easy to try but geographically and culturally uncertain.
- Host an IRL game: best control over environment but requires the user to become a game master.
- Solo TTRPG with paper or Tabletop Simulator: private and controlled but can feel like self-driven creative writing.
- CRPGs: lower friction but lack tabletop freedom and may not match tone preferences.
- Raw LLM as game master: easy to start but unreliable for state and rules over time.
- OSR or Scarlet Heroes as the first backbone: flavorful and lethal but too tracking-heavy for the first app.
- Ironsworn as the first backbone: strong solo mechanics but less system-agnostic than a Mythic-style oracle.
- Mythic GME-style oracle: currently preferred because it is solo-first, system-agnostic, and easy to keep deterministic.

## Product Implication

The strongest product opportunity is a private AI game master with explicit state, visible oracle mechanics, and a satisfying UI. It should borrow only the useful parts of solo TTRPGs, CRPGs, and LLM chat rather than copying any one format wholesale.
