import React, { useEffect, useLayoutEffect, useRef, useState } from "react"
import UserView from "./UserView"
import type { BoardCard, Card, ChatMessage, EmitFn, GameState, PlayerState, Printing, Session } from "./interfaces"

// Renders the game state built by server/game_setup.py. Like the lobby,
// nothing here talks to the soulmasters server directly: actions are `game`
// socket emits that fireball forwards to POST /game/{id} and broadcasts the
// updated state back to everyone in the soulmasters/game/{id} channel.
// Currently covers setup (zones, opening hands, the mulligan decision),
// energy plays (face-down energy, face-up Artifact Cores and core swaps),
// resting energy to pay costs (click ready energy, then confirm), converting
// energy into resources at the commander's rate, casting units and spells
// from hand (pick the card, pick or auto-pick the energy to rest as payment),
// casting reserve cards (paid in resources; Weapon/Armor/Battlefield replace
// and Remove, Feats resolve and are Removed) and the turn cycle: End turn
// passes to the opponent, whose upkeep readies their cards and resets the
// per-turn allowances before they draw.
//
// The table is laid out like a physical playmat (one per player, opponent's
// flipped): equipment on the left, commander with HP/resource badges, the
// battleground and energy field as translucent regions, piles on the right,
// and the owner's hand fanned along the bottom edge. A hover preview on the
// right shows any card at readable size. State changes animate so players can
// follow the game without reading the log: cards FLIP-animate between zones
// (keyed by uid), new cards pop in, counters pulse when they change, resting
// rotates, and turn changes flash a banner.

const RING = "soulmasters"

// The slice of GET /rules the board needs (see server/rules.py). Fetched
// rather than hardcoded so the server stays the single source of truth; if
// the fetch fails the buttons stay enabled and the server still enforces.
interface TurnRules {
  energyPlaysPerTurn: number
  firstTurnEnergyPlays: number
  reserveCastsPerRound: number
  reserveUnlockRound: number
}

const useTurnRules = (): TurnRules | null => {
  const [rules, setRules] = useState<TurnRules | null>(null)
  useEffect(() => {
    fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ method: "get", ringId: RING, path: "rules" }),
    })
      .then(res => (res.ok ? res.json() : null))
      .then(setRules)
      .catch(() => setRules(null))
  }, [])
  return rules
}

interface CardPool {
  cards: Map<string, Card>
  images: Map<string, string>
}

// Card data comes straight from the Studio tables through fireball's data
// API, the same way CardBrowser reads them.
const useCardPool = (): CardPool | null => {
  const [pool, setPool] = useState<CardPool | null>(null)
  useEffect(() => {
    Promise.all([
      fetch(`/api/data/${RING}/card`).then(res => res.json()),
      fetch(`/api/data/${RING}/printing`).then(res => res.json()),
    ])
      .then(([cardRows, printingRows]: [Card[], Printing[]]) => {
        const images = new Map<string, string>()
        for (const printing of printingRows) {
          if (printing.image && !images.has(printing.name)) {
            images.set(printing.name, `/${RING}/asset/printing/${printing.image}`)
          }
        }
        setPool({ cards: new Map(cardRows.map(card => [card.id, card])), images })
      })
      .catch(() => setPool({ cards: new Map(), images: new Map() }))
  }, [])
  return pool
}

// `flip(uid)` registers a card element; `flip(uid, "deck:bottom")` also says a
// first-seen copy should travel out of that named anchor instead of popping in.
// `flip.anchor(name)` marks a fixed spot (a face-down pile) as such an origin.
type FlipRegister = ((key: string, spawnFrom?: string) => (el: HTMLElement | null) => void) & {
  anchor: (name: string) => (el: HTMLElement | null) => void
}

// FLIP animation registry. Every card element registers under its uid; after
// each render we compare each element's rect to where that uid last was and
// play a reverse transform, so a card leaving the hand visibly travels to the
// energy field or battleground. uids are stable across zones (a unit dying
// FLIPs from the battleground to the discard). A uid seen for the first time
// travels from its registered spawn anchor (the deck, for a freshly drawn card)
// if one is known, otherwise pops in — that's all the feedback an opponent's
// hidden hand can give. An element still mid-animation contributes its current
// on-screen position as the origin, so interrupted moves stay smooth.
const useFlip = (): FlipRegister => {
  const els = useRef(new Map<string, HTMLElement>())
  const rects = useRef(new Map<string, DOMRect>())
  const spawns = useRef(new Map<string, string>()) // uid -> anchor name to fly from when first seen
  const anchors = useRef(new Map<string, HTMLElement>()) // anchor name -> element (a face-down pile)
  const mounted = useRef(false)
  useLayoutEffect(() => {
    // Snapshot anchor positions up front so a card drawn this render flies from
    // where its source pile sits right now.
    const anchorRects = new Map<string, DOMRect>()
    for (const [name, el] of anchors.current) anchorRects.set(name, el.getBoundingClientRect())

    const seen = new Set<string>()
    for (const [key, el] of els.current) {
      seen.add(key)
      let origin = rects.current.get(key)
      const running = el.getAnimations()
      if (running.length > 0) {
        origin = el.getBoundingClientRect()
        for (const animation of running) animation.cancel()
      }
      const target = el.getBoundingClientRect()
      rects.current.set(key, target)
      // A first-seen card with a known spawn anchor flies from that pile.
      const spawn = origin ? undefined : anchorRects.get(spawns.current.get(key) ?? "")
      if (origin) {
        const dx = origin.left - target.left
        const dy = origin.top - target.top
        if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
          el.animate(
            [
              { transform: `translate(${dx}px, ${dy}px)`, zIndex: "30" },
              { transform: "translate(0, 0)", zIndex: "30" },
            ],
            { duration: 450, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
          )
        }
      } else if (spawn && mounted.current) {
        const dx = spawn.left - target.left
        const dy = spawn.top - target.top
        el.animate(
          [
            { transform: `translate(${dx}px, ${dy}px)`, opacity: 0.35, zIndex: "30" },
            { transform: "translate(0, 0)", opacity: 1, zIndex: "30" },
          ],
          { duration: 450, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
        )
      } else if (mounted.current) {
        el.animate(
          [
            { opacity: 0, transform: "scale(0.4)" },
            { opacity: 1, transform: "scale(1)" },
          ],
          { duration: 350, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
        )
      }
    }
    for (const key of [...rects.current.keys()]) if (!seen.has(key)) rects.current.delete(key)
    mounted.current = true
  })
  const flip = ((key: string, spawnFrom?: string) => (el: HTMLElement | null) => {
    if (el) {
      els.current.set(key, el)
      if (spawnFrom) spawns.current.set(key, spawnFrom)
    } else {
      els.current.delete(key)
      spawns.current.delete(key)
    }
  }) as FlipRegister
  flip.anchor = (name: string) => (el: HTMLElement | null) => {
    if (el) anchors.current.set(name, el)
    else anchors.current.delete(name)
  }
  return flip
}

// Pulses an element when the watched value changes (HP, resources, counts).
const usePulse = (value: unknown) => {
  const ref = useRef<HTMLDivElement>(null)
  const prev = useRef(value)
  useEffect(() => {
    if (prev.current !== value) {
      ref.current?.animate(
        [
          { transform: "scale(1.5)", filter: "brightness(1.8)" },
          { transform: "scale(1)", filter: "brightness(1)" },
        ],
        { duration: 600, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
      )
    }
    prev.current = value
  }, [value])
  return ref
}

// Shared plumbing so every card on the table can FLIP-register and feed the
// hover preview without threading props through each zone.
interface BoardEnv {
  pool: CardPool
  flip: FlipRegister
  hover: (id: string) => void
}

const BoardCtx = React.createContext<BoardEnv | null>(null)
const useBoard = () => React.useContext(BoardCtx)!

interface CardViewProps {
  id: string
  uid?: string // registers this copy for FLIP; omit for cards that never move
  spawnFrom?: string // anchor name to fly from when this copy is first seen (e.g. a draw)
  selected?: boolean
  onClick?: () => void
  badges?: React.ReactNode // overlaid chips (HP, attack/health, labels)
}

// A card on the table: scanned image when a printing has one, otherwise a
// small text proxy. Hovering shows it full size in the preview pane.
const CardView: React.FC<CardViewProps> = ({ id, uid, spawnFrom, selected, onClick, badges }) => {
  const { pool, flip, hover } = useBoard()
  const image = pool.images.get(id)
  const card = pool.cards.get(id)
  const frame = image ? (
    <img className="w-full h-full object-cover rounded-md" src={image} alt={id} />
  ) : (
    <div className="w-full h-full rounded-md border border-border bg-navy-800 p-1.5 flex flex-col text-left">
      <div className="text-xs font-semibold leading-tight">{id}</div>
      {card?.cost != null && <div className="text-xs text-gray-400">Cost {card.cost}</div>}
      <div className="mt-auto text-[10px] text-gray-400 truncate">
        {card?.attributes || card?.type}
      </div>
    </div>
  )
  return (
    <div
      ref={uid ? flip(uid, spawnFrom) : undefined}
      className={`w-24 aspect-[5/7] shrink-0 relative rounded-md transition-transform ${
        selected ? "outline-2 outline-sky-400 z-20" : ""
      } ${onClick ? "cursor-pointer hover:outline-2 hover:outline-orange-400" : ""}`}
      title={id}
      onClick={onClick}
      onMouseEnter={() => hover(id)}
    >
      {frame}
      {badges}
    </div>
  )
}

// Face-down pile (deck, reserve, hidden hands) drawn as a stacked block with
// a count that pulses when it changes.
const Pile: React.FC<{
  count: number
  label: string
  tone?: "gold" | "orange"
  active?: boolean
  anchor?: string // FLIP anchor name so drawn cards can travel out of this pile
  onClick?: () => void
}> = ({ count, label, tone = "gold", active, anchor, onClick }) => {
  const ref = usePulse(count)
  const { flip } = useBoard()
  const face =
    tone === "orange"
      ? "border-orange-950 bg-gradient-to-br from-orange-700 to-orange-950"
      : "border-amber-950 bg-gradient-to-br from-amber-600 to-amber-900"
  return (
    <div
      ref={anchor ? flip.anchor(anchor) : undefined}
      className={`w-24 aspect-[5/7] relative rounded-md border shrink-0 ${face} ${count === 0 ? "opacity-25" : ""}
        ${active ? "outline-2 outline-sky-400" : ""} ${onClick ? "cursor-pointer" : ""}`}
      style={count > 1 ? { boxShadow: "3px 3px 0 rgba(0,0,0,0.45), 6px 6px 0 rgba(0,0,0,0.25)" } : undefined}
      onClick={onClick}
    >
      <div ref={ref} className="absolute inset-0 flex items-center justify-center text-xl font-bold text-white/90">
        {count}
      </div>
      {/* Label overlaid at the bottom instead of below, saving vertical space;
          the dark translucent strip keeps it readable over the pile art. */}
      <span className="absolute inset-x-0 bottom-0 rounded-b-md bg-black/60 text-center text-[9px] uppercase tracking-wider text-gray-200">
        {label}
      </span>
    </div>
  )
}

// A labeled slot that holds the top card of a discard/removed pile. Clicking a
// non-empty slot opens a tray of the whole pile (public info for both players),
// the same way the reserve pile does. `up` opens the tray upward for the
// owner's bottom edge and downward for the opponent's top edge.
const Slot: React.FC<{ label: string; cards?: BoardCard[]; up?: boolean }> = ({ label, cards = [], up }) => {
  const [open, setOpen] = useState(false)
  const top = cards[cards.length - 1]
  return (
    <div className="relative">
      {open && cards.length > 0 && (
        <div
          className={`absolute left-1/2 -translate-x-1/2 z-30 pane rounded-lg p-2 flex gap-2 shadow-2xl max-w-[80vw] overflow-x-auto ${
            up ? "bottom-full mb-2" : "top-full mt-2"
          }`}
        >
          {/* No uid here: the top card is FLIP-registered by the slot below, so
              registering it again in the tray would clobber that entry. */}
          {cards.map(card => (
            <CardView key={card.uid} id={card.id} />
          ))}
        </div>
      )}
      <div
        className={`w-24 aspect-[5/7] relative rounded-md border border-dashed border-white/15 shrink-0 ${
          cards.length > 0 ? "cursor-pointer" : ""
        } ${open ? "outline-2 outline-sky-400" : ""}`}
        onClick={cards.length > 0 ? () => setOpen(o => !o) : undefined}
      >
        {top && <CardView uid={top.uid} id={top.id} />}
        {/* Label overlaid at the bottom (matching Pile) to save vertical space. */}
        <span className="absolute inset-x-0 bottom-0 rounded-b-md bg-black/60 text-center text-[9px] uppercase tracking-wider text-gray-200 pointer-events-none">
          {label}
        </span>
      </div>
    </div>
  )
}

// A translucent mat region with a watermark label, like the Pitch/Graveyard
// areas on a printed playmat.
const Region: React.FC<{
  label: string
  grow?: boolean
  col?: boolean
  className?: string
  children?: React.ReactNode
}> = ({ label, grow, col, className = "", children }) => (
  <div className={`relative rounded-lg bg-white/5 ${grow ? "grow min-w-0" : ""} ${className}`}>
    <span
      className={`absolute inset-0 flex items-center justify-center font-semibold uppercase tracking-[0.3em] text-[13px] text-white/10 pointer-events-none select-none ${
        col ? "[writing-mode:vertical-lr]" : ""
      }`}
    >
      {label}
    </span>
    <div className={`relative h-full flex ${col ? "flex-col px-1 py-2 overflow-y-auto" : "p-2 overflow-x-auto"}`}>
      {/* m-auto centers the cards while keeping the start reachable once they overflow */}
      <div className={`flex m-auto ${col ? "flex-col items-center -space-y-14" : "items-center gap-2"}`}>
        {children}
      </div>
    </div>
  </div>
)

// A card in the energy field. Face-down energy shows a card back to both
// players; the owner's back is still clickable (to rest it as payment) and
// hovering it reveals the card in the preview pane, since the rulebook lets
// you look at your own face-down energy any time. Resting turns the card
// sideways, animated so paying costs reads at a glance; the outer wrapper
// carries the FLIP transform so the rotation and the travel animation don't
// fight.
interface EnergyCardProps {
  card: BoardCard
  mine: boolean
  selected?: boolean
  onClick?: () => void
}

const EnergyCard: React.FC<EnergyCardProps> = ({ card, mine, selected, onClick }) => {
  const { flip, hover } = useBoard()
  return (
    <div ref={flip(card.uid)} className={`shrink-0 transition-all duration-300 ${card.resting ? "rotate-90 mx-5" : ""}`}>
      {!card.faceUp ? (
        <div
          className={`w-24 aspect-[5/7] rounded-md border border-amber-950 bg-gradient-to-br from-amber-600 to-amber-900 ${
            selected ? "outline-2 outline-sky-400 z-20" : ""
          } ${mine && onClick ? "cursor-pointer hover:outline-2 hover:outline-orange-400" : ""}`}
          title="Face-down energy"
          onClick={mine ? onClick : undefined}
          onMouseEnter={mine ? () => hover(card.id) : undefined}
        />
      ) : (
        <CardView id={card.id} selected={selected} onClick={onClick} />
      )}
    </div>
  )
}

interface MatProps {
  player: PlayerState
  active: boolean
  flipped: boolean // opponent mat: outer edge (name, piles) at the top
  mine?: boolean // the viewer owns this mat and may see face-down energy
  selectedEnergy?: string[] // energy cards staged to swap back to hand or to rest
  onEnergyClick?: (uid: string) => void
}

const Mat: React.FC<MatProps> = ({ player, active, flipped, mine, selectedEnergy, onEnergyClick }) => {
  const { pool } = useBoard()
  const commanderId = player.commander.stages[player.commander.stage]
  const hpRef = usePulse(player.hp)
  const resourceRef = usePulse(player.resourceField)
  return (
    <div
      className={`grow basis-0 min-h-0 rounded-xl border p-2 flex gap-1 transition-all duration-500 ${
        flipped ? "flex-col bg-gradient-to-b from-navy-900 to-navy-800" : "flex-col-reverse bg-gradient-to-b from-navy-800 to-navy-900"
      } ${active ? "border-sky-400 shadow-[0_0_20px_rgba(56,140,255,0.25)]" : "border-white/10"}`}
    >
      <div className="flex items-center gap-2 px-1 shrink-0">
        <UserView user={player.user} />
      </div>

      <div className="grow min-h-0 flex gap-2">
        <Region label="Equipment" col className="w-28 shrink-0">
          {player.equipment.map(card => <CardView key={card.uid} uid={card.uid} id={card.id} />)}
        </Region>

        <div className="flex flex-col justify-center shrink-0 px-1">
          <CardView
            id={commanderId}

            badges={
              <>
                <div
                  ref={hpRef}
                  className="absolute -bottom-2 -left-2 rounded-full bg-emerald-800 border-2 border-emerald-400/60 px-2 py-0.5 text-sm font-bold text-emerald-50 shadow-md whitespace-nowrap"
                  title={`Life: ${player.hp}/${player.maxHp}`}
                >
                  ♥ {player.hp}
                </div>
                <div
                  ref={resourceRef}
                  className="absolute -bottom-2 -right-2 rounded-full bg-sky-900 border-2 border-sky-400/60 px-2 py-0.5 text-sm font-bold text-sky-50 shadow-md whitespace-nowrap"
                  title={`${player.resource}: ${player.resourceField} in play, ${player.resourceDeck} left in the resource deck`}
                >
                  {player.resourceField}/{player.resourceField + player.resourceDeck}
                </div>
              </>
            }
          />
        </div>

        <div className={`grow min-w-0 flex gap-2 ${flipped ? "flex-col-reverse" : "flex-col"}`}>
          <Region label="Battleground" grow className="min-h-38 basis-0">
            {player.battlefield && (
              <>
                <CardView
                  uid={player.battlefield.uid}
                  id={player.battlefield.id}

                  badges={
                    <div className="absolute inset-x-0 bottom-0 rounded-b-md bg-black/60 text-center text-[9px] uppercase tracking-wide text-amber-200 pointer-events-none">
                      Battlefield
                    </div>
                  }
                />
                <div className="w-px self-stretch bg-white/10 shrink-0" />
              </>
            )}
            {player.battleground.map(card => {
              const data = pool.cards.get(card.id)
              return (
                <CardView
                  key={card.uid}
                  uid={card.uid}
                  id={card.id}
                  badges={
                    <>
                      {data?.attack != null && (
                        <div className="absolute top-1 right-1 rounded-full bg-sky-900 border border-sky-400/60 px-1.5 text-xs font-bold text-sky-50">
                          {data.attack}
                        </div>
                      )}
                      {card.enteredThisRound && (
                        <div
                          className="absolute inset-0 rounded-md outline-2 outline-orange-400 pointer-events-none"
                          title="Entered this round"
                        />
                      )}
                    </>
                  }
                />
              )
            })}
          </Region>
          <Region label={`Energy · ${player.energyField.length}`} grow className="min-h-38 basis-0">
            {player.energyField.map(card => (
              <EnergyCard
                key={card.uid}
                card={card}
                mine={!!mine}
                selected={selectedEnergy?.includes(card.uid)}
                onClick={onEnergyClick ? () => onEnergyClick(card.uid) : undefined}
              />
            ))}
          </Region>
        </div>
      </div>
    </div>
  )
}

// The strip along a player's table edge: reserve pile on the left, the hand
// centered, discard/removed/deck on the right. The opponent's strip is the
// same shape mirrored to the top of the table; `hand` carries either the
// owner's fanned cards or face-down backs for hidden hands.
const EdgeRow: React.FC<{
  player: PlayerState
  reserve: React.ReactNode
  hand: React.ReactNode
  flipped?: boolean // opponent's top edge: pile trays open downward
}> = ({ player, reserve, hand, flipped }) => (
  <div className="shrink-0 grid grid-cols-[1fr_auto_1fr] items-center gap-3 px-3">
    <div className="justify-self-end">{reserve}</div>
    <div className="min-w-0">{hand}</div>
    <div className="justify-self-start flex items-center gap-2">
      <Pile count={player.deck.length} label="Deck" anchor={flipped ? "deck:top" : "deck:bottom"} />
      <Slot label="Discard" cards={player.discard} up={!flipped} />
      <Slot label="Removed" cards={player.removed} up={!flipped} />
    </div>
  </div>
)

// A hidden hand fanned as card backs, still FLIP-registered so draws pop in
// and played cards travel from the hand to where they land.
const HiddenHand: React.FC<{ cards: BoardCard[]; count: number; flip: FlipRegister; spawnFrom?: string }> = ({
  cards,
  count,
  flip,
  spawnFrom,
}) => (
  // Same fixed width as the owner's hand: 7 cards fit without overlap, an 8th+
  // falls back to the fanned overlap. The count label is overlaid at the bottom
  // (like the pile labels) instead of below, saving vertical space.
  <div className={`relative flex justify-center w-[45rem] ${cards.length > 7 ? "-space-x-10" : "gap-2"}`}>
    {cards.map((card, i) => (
      <div
        key={card.uid || i}
        ref={card.uid ? flip(card.uid, spawnFrom) : undefined}
        className="w-24 aspect-[5/7] shrink-0 rounded-md border border-amber-950 bg-gradient-to-br from-amber-600 to-amber-900"
      />
    ))}
    <HandLabel count={count} />
  </div>
)

// The hand's card-count chip, overlaid at the bottom center of the fanned
// cards with a dark translucent strip for contrast, matching the pile labels.
const HandLabel: React.FC<{ count: number }> = ({ count }) => (
  <span className="absolute bottom-0 left-1/2 -translate-x-1/2 z-30 rounded bg-black/60 px-2 text-[9px] uppercase tracking-wider text-gray-200 pointer-events-none">
    Hand · {count}
  </span>
)

// The hover preview: whatever card the pointer last touched, at readable size.
const PreviewPane: React.FC<{ id: string | null }> = ({ id }) => {
  const { pool } = useBoard()
  const image = id ? pool.images.get(id) : undefined
  const card = id ? pool.cards.get(id) : undefined
  return (
    <div className={`w-full aspect-[5/7] shrink-0 rounded-xl overflow-hidden ${id ? "pane" : "invisible"}`}>
      {image ? (
        <img className="w-full h-full object-cover" src={image} alt={id ?? ""} />
      ) : id ? (
        <div className="w-full h-full p-3 flex flex-col gap-2 bg-navy-800 text-left">
          <div className="flex items-start justify-between gap-2">
            <div className="font-bold leading-tight">{id}</div>
            {card?.cost != null && <div className="shrink-0 rounded-full bg-gray-700 px-2 font-semibold">{card.cost}</div>}
          </div>
          <div className="text-sm text-gray-400">{card?.attributes || card?.type}</div>
          <div className="text-sm whitespace-pre-wrap overflow-y-auto">{card?.text}</div>
          {(card?.attack != null || card?.health != null) && (
            <div className="mt-auto flex justify-between font-semibold">
              <span className="text-red-300">{card?.attack ?? "—"} ⚔</span>
              <span className="text-emerald-300">{card?.health ?? "—"} ♥</span>
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}

const LogView: React.FC<{ log: ChatMessage[] }> = ({ log }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" })
  }, [log.length])
  return (
    <div className="pane rounded-lg p-2 grow flex flex-col min-h-0">
      <div ref={ref} className="grow overflow-auto space-y-2.5">
        {log.map((entry, i) =>
          entry.user ? (
            <div key={i} className="leading-snug">
              <UserView user={entry.user} />{" "}
              <span className="align-middle text-gray-300">{entry.msg}</span>
            </div>
          ) : (
            // System messages (no player) read as section markers: centered with
            // a separator line above them.
            <div key={i} className="flex items-center gap-2 pt-1 text-center text-gray-400">
              <div className="grow h-px bg-white/10" />
              <span className="uppercase tracking-wider text-[11px]">{entry.msg}</span>
              <div className="grow h-px bg-white/10" />
            </div>
          ),
        )}
      </div>
    </div>
  )
}

// Transient center-table banner for turn changes (and the game result).
const Banner: React.FC<{ text: string; sticky?: boolean }> = ({ text, sticky }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.animate(
      sticky
        ? [
            { opacity: 0, transform: "scale(0.8)" },
            { opacity: 1, transform: "scale(1)" },
          ]
        : [
            { opacity: 0, transform: "scale(0.8)" },
            { opacity: 1, transform: "scale(1)", offset: 0.15 },
            { opacity: 1, transform: "scale(1)", offset: 0.8 },
            { opacity: 0, transform: "scale(1.05)" },
          ],
      { duration: sticky ? 400 : 1600, easing: "ease-out", fill: "forwards" },
    )
  }, [sticky])
  return (
    <div className="absolute inset-0 z-40 flex items-center justify-center pointer-events-none">
      <div ref={ref} className="rounded-2xl bg-black/75 px-8 py-4 text-3xl font-bold text-cream-100 shadow-2xl">
        {text}
      </div>
    </div>
  )
}

interface GameBoardProps {
  id?: string
  session?: Session
  emit: EmitFn
  gamestate: GameState
}

const GameBoard: React.FC<GameBoardProps> = ({ id, session, emit, gamestate }) => {
  const pool = useCardPool()
  const rules = useTurnRules()
  const flip = useFlip()
  const [preview, setPreview] = useState<string | null>(null)
  const [returning, setReturning] = useState<string[]>([])
  // Energy play staging: a hand card picked to place, and (for a face-up
  // Artifact Core) an energy card picked to swap back to hand.
  const [playing, setPlaying] = useState<string | null>(null)
  const [swap, setSwap] = useState<string | null>(null)
  // Ready energy cards staged to rest (paying a cost), confirmed as one action.
  const [restUids, setRestUids] = useState<string[]>([])
  // A reserve card staged to cast (paid in resources, not energy).
  const [castingReserve, setCastingReserve] = useState<string | null>(null)
  // Whether the viewer's reserve tray (opened from the reserve pile) is shown.
  const [reserveOpen, setReserveOpen] = useState(false)
  // The detail of the last rejected action. The `game` emit only acks the
  // sender when the server rejects (successful actions are broadcast as new
  // state), so a stale error is cleared when fresh state arrives.
  const [actionError, setActionError] = useState<string | null>(null)
  useEffect(() => {
    setActionError(null)
    // Fresh state may have rested or removed a staged card; drop it
    setRestUids(uids =>
      uids.filter(uid =>
        gamestate?.players?.some(p => p.energyField.some(c => c.uid === uid && !c.resting))))
  }, [gamestate])

  // Flash a banner when the active player changes, so passing the turn is
  // unmissable without checking the status line.
  const [turnBanner, setTurnBanner] = useState<{ text: string; key: number } | null>(null)
  const bannerKey = useRef(0)
  const bannerTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const prevActive = useRef<number | null | undefined>(undefined)
  useEffect(() => {
    const active = gamestate?.phase === "main" ? gamestate.activePlayer : null
    const changed = prevActive.current !== undefined && active != null && active !== prevActive.current
    prevActive.current = active
    if (!changed || active == null) return
    const username = gamestate.players[active].user.username
    const text = username === session?.user?.username ? "Your turn" : `${username}'s turn`
    setTurnBanner({ text, key: ++bannerKey.current })
    clearTimeout(bannerTimer.current)
    bannerTimer.current = setTimeout(() => setTurnBanner(null), 1600)
  }, [gamestate?.phase, gamestate?.activePlayer, gamestate?.players, session?.user?.username])
  useEffect(() => () => clearTimeout(bannerTimer.current), [])

  if (!pool || !gamestate?.players?.length) return <div />

  // fireball forwards this to POST /game/{id}, broadcasts the returned state to
  // the channel on success, and acks us with { error: { detail } } on reject.
  const send = (data: object) => {
    setActionError(null)
    emit("game", { method: "post", ringId: RING, path: `game/${id}`, data }, resp => {
      const error = (resp as { error?: { detail?: string } }).error
      if (error) setActionError(error.detail ?? "The action could not be completed.")
    })
  }
  const myIndex = gamestate.players.findIndex(player => player.user.username === session?.user?.username)
  // Spectators watch from seat 0's side of the table
  const bottom = myIndex >= 0 ? myIndex : 0
  const top = gamestate.players.length - 1 - bottom
  const me = myIndex >= 0 ? gamestate.players[myIndex] : null
  const opponent = gamestate.players[top]
  const bottomPlayer = gamestate.players[bottom]

  const mulliganing = gamestate.phase === "mulligan" && !!me && !me.mulliganed
  const toggle = (uid: string) =>
    setReturning(uids => (uids.includes(uid) ? uids.filter(u => u !== uid) : [...uids, uid]))
  const confirmMulligan = (uids: string[]) => {
    send({ action: "mulligan", data: uids })
    setReturning([])
  }

  const myTurn = gamestate.phase === "main" && myIndex >= 0 && gamestate.activePlayer === myIndex
  // The per-turn energy allowance: 2, but only 1 on the game's first turn
  // (server/rules.py; play_energy enforces it — this only gates the UI).
  const firstTurn = gamestate.round === 1 && gamestate.activePlayer === gamestate.firstPlayer
  const energyAllowance = rules ? (firstTurn ? rules.firstTurnEnergyPlays : rules.energyPlaysPerTurn) : null
  const canPlayEnergy = myTurn && (energyAllowance === null || (me?.energyPlays ?? 0) < energyAllowance)
  const playingCard = myTurn ? me?.hand.find(card => card.uid === playing) : undefined
  const playingData = playingCard ? pool.cards.get(playingCard.id) : undefined
  // Only Artifact Cores may be played face up, which is also when a swap is allowed
  const playingCore = playingData?.type === "Core"
  // Units and spells are castable by resting energy equal to their cost; a
  // null cost means the Studio cell is still unset, so the card can't be
  // priced (the server rejects it too).
  const castCost = playingData?.type === "Unit" || playingData?.type === "Spell" ? playingData.cost : null
  const readyEnergy = me ? me.energyField.filter(card => !card.resting).length : 0
  // The commander's energy → resource conversion rate ("3:1" on the card),
  // read from the current evolution stage and falling back through earlier
  // stages when a Studio cell is unset (mirrors server/game.py conversion_cost).
  let conversionCost: number | null = null
  if (me) {
    for (let stage = me.commander.stage; stage >= 0 && conversionCost == null; stage--) {
      const match = pool.cards.get(me.commander.stages[stage])?.["conversion-rate"]?.match(/\d+/)
      if (match) conversionCost = Number(match[0])
    }
  }
  const stageEnergy = (uid: string) => {
    setSwap(null)
    setRestUids([])
    setCastingReserve(null)
    setPlaying(current => (current === uid ? null : uid))
  }
  const playEnergy = (faceUp: boolean) => {
    send({ action: "energy", data: { uid: playing, faceUp, swap: faceUp ? swap : null } })
    setPlaying(null)
    setSwap(null)
    setRestUids([])
  }
  const cast = () => {
    if (castCost == null || !me) return
    // Payment: the energy cards the player clicked, topped up with ready
    // energy in field order until the cost is covered.
    const payment = [...restUids]
    for (const card of me.energyField) {
      if (payment.length >= castCost) break
      if (!card.resting && !payment.includes(card.uid)) payment.push(card.uid)
    }
    send({ action: "cast", data: { uid: playing, energy: payment } })
    setPlaying(null)
    setRestUids([])
  }
  // Resting energy is how costs are paid (rulebook pp. 12, 15, 17) and is
  // allowed on either player's turn; the server rejects already-resting cards.
  const canRest = gamestate.phase === "main" && !!me
  const toggleRest = (uid: string) => {
    if (me?.energyField.some(card => card.uid === uid && !card.resting))
      setRestUids(uids => (uids.includes(uid) ? uids.filter(u => u !== uid) : [...uids, uid]))
  }
  const restEnergy = () => {
    send({ action: "rest", data: restUids })
    setRestUids([])
  }
  // Converting rests energy like a cost, so it shares the rest staging: once
  // exactly the rate is picked (and a resource is left to generate), the
  // staged cards can be converted instead of plain-rested.
  const convertEnergy = () => {
    send({ action: "convert", data: restUids })
    setRestUids([])
  }
  // Reserve casting: pick a reserve card, pay its cost in resources. The
  // server enforces the once-per-round / round-2 limits; rules only gate the UI.
  const reserveCard = myTurn ? me?.reserve.find(card => card.uid === castingReserve) : undefined
  const reserveCost = reserveCard ? (pool.cards.get(reserveCard.id)?.cost ?? null) : null
  const reserveLocked = !!rules && gamestate.round < rules.reserveUnlockRound
  const reserveUsed = !!rules && (me?.reserveCasts ?? 0) >= rules.reserveCastsPerRound
  const stageReserve = (uid: string) => {
    setPlaying(null)
    setSwap(null)
    setRestUids([])
    setCastingReserve(current => (current === uid ? null : uid))
  }
  const castReserve = () => {
    send({ action: "reserve", data: { uid: castingReserve } })
    setCastingReserve(null)
    setReserveOpen(false)
  }
  const endTurn = () => {
    setPlaying(null)
    setSwap(null)
    setRestUids([])
    setCastingReserve(null)
    send({ action: "end" })
  }

  const status = gamestate.phase === "over"
    ? gamestate.winner != null
      ? `${gamestate.players[gamestate.winner].user.username} wins the game`
      : "The game is over"
    : mulliganing
      ? "Mulligan: select any cards to put on the bottom of your deck and redraw, or keep your hand."
      : gamestate.phase === "mulligan" ?
        "Waiting for your opponent's mulligan…"
        : `Round ${gamestate.round} — ${gamestate.players[gamestate.activePlayer ?? gamestate.firstPlayer].user.username}'s turn`

  return (
    <BoardCtx.Provider value={{ pool, flip, hover: setPreview }}>
      <div className="relative h-full min-h-0 flex gap-2 p-2 bg-navy-900">
        <div className="grow min-w-0 flex flex-col gap-2 overflow-y-auto">
          <EdgeRow
            player={opponent}
            reserve={<Pile count={opponent.reserve.length} label="Reserve" tone="orange" />}
            hand={<HiddenHand cards={opponent.hand} count={opponent.hand.length} flip={flip} spawnFrom="deck:top" />}
            flipped
          />

          <Mat player={opponent} active={gamestate.activePlayer === top} flipped />

          {/* The prompt bar: status plus whatever action is currently staged. */}
          <div className="self-center z-20 shrink-0 max-w-full flex flex-wrap items-center justify-center gap-2 rounded-full border border-white/10 bg-black/80 px-4 py-1.5 shadow-xl">
            <span className="whitespace-nowrap">{status}</span>
            {actionError &&
              <span className="flex items-center gap-2 bg-red-900 text-red-100 px-2 py-0.5 rounded">
                {actionError}
                <button
                  className="text-red-200/80 hover:text-red-100 leading-none"
                  title="Dismiss"
                  onClick={() => setActionError(null)}
                >
                  ✕
                </button>
              </span>}
            {mulliganing &&
              <>
                <button className="sm" disabled={returning.length === 0} onClick={() => confirmMulligan(returning)}>
                  Return {returning.length} card{returning.length === 1 ? "" : "s"}
                </button>
                <button className="sm" onClick={() => confirmMulligan([])}>Keep hand</button>
              </>}
            {playingCard &&
              <>
                {playingCore && canPlayEnergy &&
                  <span className="text-gray-400 whitespace-nowrap">
                    {swap ? "Swapping 1 energy card back to hand" : "Click your energy to swap a card back"}
                  </span>}
                {castCost != null && castCost > 0 &&
                  <span className="text-gray-400 whitespace-nowrap">
                    {restUids.length}/{castCost} energy picked to rest
                  </span>}
                {castCost != null &&
                  <button className="sm" disabled={readyEnergy < castCost || restUids.length > castCost} onClick={cast}>
                    Cast{castCost > 0 ? ` — rest ${castCost} energy` : ""}
                  </button>}
                {canPlayEnergy && <button className="sm" onClick={() => playEnergy(false)}>Play face down as energy</button>}
                {playingCore && canPlayEnergy &&
                  <button className="sm" onClick={() => playEnergy(true)}>Play face up{swap ? " and swap" : ""}</button>}
                <button className="sm" onClick={() => stageEnergy(playingCard.uid)}>Cancel</button>
              </>}
            {reserveCard && me &&
              <>
                <span className="text-gray-400 whitespace-nowrap">
                  {reserveLocked
                    ? `Reserve cards unlock in round ${rules?.reserveUnlockRound}`
                    : reserveUsed
                      ? "Reserve cast already used this round"
                      : reserveCost != null
                        ? `Costs ${reserveCost} ${me.resource} — you have ${me.resourceField}`
                        : `${reserveCard.id} has no cost yet`}
                </span>
                <button
                  className="sm"
                  disabled={reserveLocked || reserveUsed || reserveCost == null || me.resourceField < reserveCost}
                  onClick={castReserve}
                >
                  Cast from reserve
                </button>
                <button className="sm" onClick={() => setCastingReserve(null)}>Cancel</button>
              </>}
            {restUids.length > 0 && !playingCard && me &&
              <>
                <span className="text-gray-400 whitespace-nowrap">Resting energy pays that much 💠</span>
                {conversionCost != null && restUids.length === conversionCost && me.resourceDeck > 0 &&
                  <button
                    className="sm"
                    onClick={convertEnergy}
                    title={`Rest ${conversionCost} energy to generate 1 ${me.resource}`}
                  >
                    Convert into 1 {me.resource}
                  </button>}
                <button className="sm" onClick={restEnergy}>
                  Rest {restUids.length} energy
                </button>
                <button className="sm" onClick={() => setRestUids([])}>Cancel</button>
              </>}
            {myTurn && me && !playingCard && !reserveCard &&
              <>
                {energyAllowance !== null &&
                  <span className="text-gray-400 whitespace-nowrap">
                    Energy plays {me.energyPlays}/{energyAllowance}
                  </span>}
                <button className="sm" onClick={endTurn}>End turn</button>
              </>}
          </div>

          <Mat
            player={bottomPlayer}
            active={gamestate.activePlayer === bottom}
            flipped={false}
            mine={!!me}
            selectedEnergy={playingCore ? (swap ? [swap] : []) : restUids}
            onEnergyClick={
              playingCore
                ? uid => setSwap(current => (current === uid ? null : uid))
                : canRest
                  ? toggleRest
                  : undefined
            }
          />

          {/* The viewer's table edge: reserve pile (click to open its tray),
              the hand fanned in the center, and the piles on the right. */}
          <EdgeRow
            player={bottomPlayer}
            reserve={
              <div className="relative">
                {reserveOpen && me && (
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-30 pane rounded-lg p-2 flex gap-2 shadow-2xl">
                    {me.reserve.length === 0 && (
                      <span className="text-sm text-gray-500 px-2 whitespace-nowrap">Reserve is empty</span>
                    )}
                    {me.reserve.map(card => (
                      <CardView
                        key={card.uid}
                        uid={card.uid}
                        id={card.id}
                        selected={card.uid === castingReserve}
                        onClick={myTurn ? () => stageReserve(card.uid) : undefined}
                      />
                    ))}
                  </div>
                )}
                <Pile
                  count={bottomPlayer.reserve.length}
                  label="Reserve"
                  tone="orange"
                  active={reserveOpen}
                  onClick={me ? () => setReserveOpen(open => !open) : undefined}
                />
              </div>
            }
            hand={
              me ? (
                // Fixed width fits 7 w-24 cards with gap-2 (45rem); an 8th+ card
                // falls back to the fanned overlap. The count label is overlaid
                // at the bottom (like the pile labels) to save vertical space.
                <div className={`relative flex justify-center w-[45rem] ${me.hand.length > 7 ? "-space-x-10" : "gap-2"}`}>
                  {me.hand.map((card: BoardCard) => (
                    <CardView
                      key={card.uid}
                      uid={card.uid}
                      spawnFrom="deck:bottom"
                      id={card.id}
                      selected={mulliganing ? returning.includes(card.uid) : card.uid === playing}
                      onClick={mulliganing ? () => toggle(card.uid) : myTurn ? () => stageEnergy(card.uid) : undefined}
                    />
                  ))}
                  <HandLabel count={me.hand.length} />
                </div>
              ) : (
                <HiddenHand cards={bottomPlayer.hand} count={bottomPlayer.hand.length} flip={flip} spawnFrom="deck:bottom" />
              )
            }
          />
        </div>

        <div className="w-80 shrink-0 flex flex-col gap-2 min-h-0">
          <PreviewPane id={preview} />
          <LogView log={gamestate.log} />
        </div>

        {turnBanner && <Banner key={turnBanner.key} text={turnBanner.text} />}
        {gamestate.phase === "over" && <Banner sticky text={status} />}
      </div>
    </BoardCtx.Provider>
  )
}

export default GameBoard
