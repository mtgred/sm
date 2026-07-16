# Soulmasters — Full Rules Implementation TODO

Roadmap for taking the game from its current state (deckbuilding, lobby, setup,
mulligan, energy plays, turn passing) to a complete implementation of the
RuleBook. Server logic lives in `server/game.py` / `server/game_setup.py`
(state = plain dict mutated in place, actions return state or `{"error": ...}`);
the board UI in `frontend/src/GameBoard.tsx`. Rule constants belong in
`server/rules.py`, exposed via `GET /rules`.

## Already done

- [x] Deck CRUD + authoritative validation (deck size 25/25, rarity copy
      limits, Celestial limit, faction legality, mercenary limit, core-energy
      count, reserve slots incl. casual, specializations)
- [x] Card pool from Studio tables (`studio.py`), CardBrowser + DeckBuilder UI
- [x] Lobby: create / join / leave / deck select / start (with deck re-check)
- [x] Game setup: shuffled snapshot decks, resource deck counters, commander
      evolution stages, face-down reserve, random first player, 5-card hands
- [x] Mulligan phase (one redraw, bottom-of-deck + shuffle)
- [x] Energy plays: face-down any card, face-up Artifact Cores, core swap
      (inherits resting), per-turn allowance (1 on the game's first turn)
- [x] End turn: upkeep ready-all, energy allowance reset, 2-card draw,
      deck-out loss (p. 11)
- [x] GameBoard: zones, hidden information (opponent hand / face-down energy),
      mulligan UI, energy staging UI, action error surface, game log

## Milestone 1 — Resources & casting (pp. 12, 15, 17–18)

The economic core: nothing else can be cast until costs can be paid.

- [x] **Rest energy to pay costs**: choose/rest N ready energy cards; energy
      readies in upkeep (ready-all already exists)
- [ ] **Convert energy → resources**: pay the commander's conversion rate
      (`conversion_rate`, current evolution stage) to move 1 resource card
      deck → field; allowed any time, even during upkeep
- [ ] **Generate / spend resources**: move resource deck ↔ field counters;
      ignore generate instructions when the resource deck is empty (p. 12)
- [ ] **Cast a unit**: main phase, your turn only; rest energy = cost;
      battleground capacity 5; enters with summoning sickness (track
      `enteredThisRound` / rest-skill lockout)
- [ ] **Cast a spell**: main phase, your turn only; resolve then discard
- [ ] **Cast an ability**: any time, including opponent's turn / in response
      (full timing comes with the stack in Milestone 3); resolve then discard
- [ ] **Artifact Cores are never cast** — energy-field placement only (done)
- [ ] **Cast reserve cards**: pay Resources (not energy) equal to cost; max 1
      per round; not before your second turn; Weapon/Armor/Battlefield go to
      their zone and **Remove** the previous one of that type; Feats resolve
      then are Removed; reserve deck is browsable any time
- [ ] Removed-from-game zone per player (for Remove effects)
- [ ] Track per-round flags on the player: reserve cast used, once-per-round
      skills (reset in upkeep)
- [ ] UI: cast-from-hand flow (pick card → pick energy to rest or auto-rest →
      confirm), resource conversion button, reserve deck browser + cast,
      equipment/battlefield replacement, removed-zone display

## Milestone 2 — Combat (pp. 21–24)

- [ ] **Declare attack**: rest attacker (commander or unit); any number of
      combats per turn, one attack at a time; combat as its own phase
      alternating freely with main phases
- [ ] **Attack legality**: only resting units are attackable (commanders
      always); no attacking on the game's first turn; summoning sickness
      blocks attacking (unless Haste)
- [ ] **Six combat steps** as explicit state (`combat` sub-state on the game):
      Declare → Pre-Defender (ON ATTACK triggers) → Defender (Intercept /
      redirect & negate window) → Post-Defender → Combat Damage → End of
      Combat (END OF COMBAT + ON KO triggers)
- [ ] **Attack damage**: attacker Atk to victim; commander victim loses HP;
      unit victim KO'd iff damage ≥ Health (damage never accumulates)
- [ ] **Damage shields** (p. 23): play hand cards as shields up to the
      victim's Shield Capacity *per damage instance*; shield Shield Power
      each, then discard; announce the damage source
- [ ] **Conjure**: commander generates N resources as it attacks (not a
      trigger; not optional)
- [ ] **KO handling**: unit → discard pile; distinguish KO vs Destroy vs
      Sacrifice vs Remove (only KO fires ON KO)
- [ ] **Commander HP & evolution** (p. 11): at 0 HP evolve to next stage
      (reset HP to new max, excess damage dropped, draw 1, generate 1
      resource); no stages left → lose; heals capped at max HP
- [ ] **Combat keywords**: Armor (flat damage reduction, works on
      unpreventable), Duelist, Haste, Heavy, Initiative, Intercept (redirect =
      new damage instance), Piercing N (ignores first N shield), Riposte,
      Scout, Stealth (ignore Taunt; blocks Intercept), Taunt (only while
      resting)
- [ ] UI: attack declaration (drag/click attacker → target), combat-step
      indicator, shield-play prompt, damage/KO animation, HP + evolution
      display, resting rotation on battleground cards

## Milestone 3 — Priority, the stack & responses (pp. 18, 25–26)

Prerequisite for abilities "in response", counters, and triggered skills.

- [ ] **Priority system**: active player gets priority first each step/phase;
      pass-pass → top of stack resolves (or phase/step advances); casting or
      activating passes priority to the opponent first
- [ ] **The stack**: skills/cards resolve LIFO; energy plays, resting energy,
      resource conversion and energy skills bypass the stack (priority stays
      with the same player)
- [ ] **Pending-decision framework**: server-driven prompts per player
      (`prompts` field exists, unused) — "you have priority", "choose
      targets", "choose mode", "play shields?", "order triggers"; every
      hidden-information choice must be a server round-trip
- [ ] **Targets** (p. 19): legal targets chosen on play; can't play without
      legal targets; targets re-checked on resolution ("do as much as you
      can")
- [ ] **Modes** (p. 20): "Choose 1 —" cards; mode picked at cast time
- [ ] **Triggered skills** (p. 28): trigger instances created on events, go on
      the stack at next priority in APNAP order; not optional; trigger costs
      ("If you pay …") as nested windows
- [ ] **Damage prevention** (p. 20): announce source; multi-target sources
      announce which target
- [ ] **Counter / Negate** actions on stack items and attacks
- [ ] UI: stack visualization, priority/pass banner ("respond or pass"),
      target picker, mode picker, trigger-order picker, auto-pass settings
      (e.g. "don't ask when I have no playable responses") so play isn't
      unbearably slow

## Milestone 4 — Skills engine & card effects (pp. 17–20, 27–30)

The big one: executable rules text. Cards in Studio carry free text, so
effects need a card-implementation registry keyed by card id (like uprising),
with shared primitives.

- [ ] **Effect primitives**: draw, mill, discard, heal, deal damage, KO,
      destroy, sacrifice, return, shock, ready/rest, attach, reforge, buff
      (+Atk/+Armor "this combat" — needs a temporary-modifier layer), generate
      resource, create token
- [ ] **Activated skills** (`cost: effect`): rest-self costs blocked by
      summoning sickness (no Haste), pay energy / resources / discard costs
- [ ] **Skill bubbles / conditions** (p. 27): ON ATTACK, ON KO, ON ENTER FROM
      HAND, ON UPKEEP, YOUR TURN, IN HAND, IN DISCARD, PRE-DEFENDER, DEFENDER,
      ONCE PER ROUND
- [ ] **Energy skills & crystals** (p. 29): energy-field cards rest for 💠;
      "add 💠" skills create crystals; no stack, immediate; crystals expire at
      end of each phase/step
- [ ] **Traps** (p. 30): skills active only while face down in the energy
      field; flip face up to activate
- [ ] **Hexes** (p. 34): spells/feats that PLACE ON BATTLEGROUND; persist, not
      units, don't count toward the 5-unit cap
- [ ] **Animated spells** (p. 34): on battleground count as units (respect the
      5 cap when cast; excluded from "put a unit from hand/discard" effects)
- [ ] **Golem Cores** (p. 33): Artifact Cores that can become battleground
      units (via their own skills, e.g. Phase)
- [ ] **Tokens** (p. 33): resource card flipped as a token unit (e.g. Skeleton
      Token); off-battleground resource cards return to the resource deck at
      next priority
- [ ] **Phase / Master Phaser** (pp. 31–32): swap attacker with Phase card(s)
      from the energy field mid-attack, cost-difference energy math, phased-in
      resting attack continuation, ON PHASE IN
- [ ] **Attachments** (p. 35): cards under cards, move/discard together
- [ ] **Status/attribute rules**: Guard (once per round, largest single
      Guard), Guardian (undiscoverable in searches; remove on 2nd KO), Null,
      Resistance (untargetable except Feats), Shock, Unique (one per Unique
      type per player)
- [ ] **Card registry**: per-card implementations for the released sets, plus
      a fallback so unimplemented cards are visibly "manual/no-op" rather than
      silently wrong; tests per card
- [ ] UI: activated-skill affordances on cards (buttons/menu), trap flip,
      token rendering, attachment stacks, temporary-buff badges, crystal
      counter

## Milestone 5 — Game flow completion

- [ ] **Upkeep as a real phase**: ON UPKEEP triggers, once-per-round resets,
      energy-skill window, then Draw (currently upkeep+draw are collapsed
      into `end_turn`)
- [ ] **End of Turn phase** (p. 14): both players may act before energy
      readies in the opponent's upkeep
- [ ] **Concede** (p. 35): explicit action; wire `leave_game` mid-game to a
      concession/win for the remaining player rather than just a log line
- [ ] **Win/loss surface**: all paths (HP with no evolutions, deck-out,
      concede) set `phase: "over"` + `winner` consistently; block further
      actions; lobby list shows finished games sensibly
- [ ] Turn timer / inactivity handling (decide policy; needs the prompt
      framework)
- [ ] Rematch / return-to-lobby flow

## Milestone 6 — Polish & hardening

- [ ] **Hidden-information audit**: state is currently broadcast whole —
      opponent hand contents, face-down energy ids, deck order and reserve
      contents are visible on the wire. Filter per-viewer before returning
      state (per-seat redaction in `POST /game/{id}` responses / fireball
      broadcast), or accept and document it
- [ ] Server-side rule enforcement review: every UI affordance has a matching
      server check (the pattern used by `play_energy`)
- [ ] Test coverage: engine unit tests per milestone (combat matrix, stack
      ordering, keyword interactions), plus API-level tests via `TestClient`
      + fake Mongo (`server/tests/conftest.py`)
- [ ] Game log quality: every state change logged, hidden info never leaked
      in logs (face-down plays already handled)
- [ ] Board UX: card zoom/inspect (rules text is unreadable at w-24), discard
      pile viewer, opponent reserve/discard counts, keyboard shortcuts,
      responsive layout for the tall two-panel board
- [ ] Spectator mode check across all new prompts (spectators must never be
      prompted or shown hidden info)
- [ ] Reconnection: rejoining a running game restores prompts/priority state

## Open questions

- [ ] How much of the card pool needs scripted effects for v1? (Suggest:
      implement the starter-deck sets first, mark the rest unplayable or
      manual.)
- [ ] Manual-mode fallback (uprising-style "both players click through
      everything") vs. strict automation for unimplemented cards?
- [ ] Casual 5-card reserve variant is validated at deckbuilding; confirm no
      in-game differences beyond deck contents.
- [ ] The comprehensive rulebook at soulmasterstcg.com — the learn-to-play
      book explicitly skips edge cases; source it before Milestone 4 to pin
      down trigger/priority corner cases.
