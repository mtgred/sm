import React, { useEffect, useMemo, useRef, useState } from "react"

// ---------------------------------------------------------------------------
// Soulmasters deckbuilder, laid out like jinteki.net/deckbuilder: a sliding
// viewport with the deck collection on the left, the selected decklist in the
// middle, and an edit panel (name / commander / typeahead / parsed textarea)
// that slides in from the right while editing.
//
// Talks to the standalone API (server/main.py, port 4005); override the base
// URL by setting window.SM_API_URL before this module loads. The server stays
// authoritative on rules via POST /decks/validate; the local checks only
// color lines and cap typeahead quantities.
// ---------------------------------------------------------------------------

declare global {
  interface Window {
    SM_API_URL?: string
  }
}

const API_BASE = window.SM_API_URL ?? "http://localhost:4005"

// -- API types (mirror of server/models.py serialization)
type CardType = "Commander" | "Unit" | "Spell" | "Ability" | "Core" | "Reserve" | "Token"

interface Printing {
  card_number: string
  set: string | null
  image: string | null
}

interface ApiCard {
  id: string // the card's name; stage-suffixed for commanders
  card_type: CardType
  faction: string
  rarity: string | null
  cost: number | null
  attack: number | null
  shield_capacity: number | null
  shield_power: number | null
  health: number | null
  faction_subtypes: string | null
  attributes: string[]
  rules_text: string
  specialization: string | null
  resource_count: number | null
  mercenary_limit: number | null
  core_energy: number | null
  hp: number | null
  conversion_rate: string | null
  printings: Printing[]
}

interface DeckEntry {
  card_id: string
  count: number
}

interface ValidationIssue {
  rule: string
  severity: "error" | "warning"
  message: string
  cards: string[]
}

interface DeckPayload {
  name: string
  commander_id: string
  main_deck: DeckEntry[]
  reserve_deck: string[]
  casual: boolean
}

interface SavedDeck extends DeckPayload {
  id: string
  owner: string
  is_valid: boolean
  issues: ValidationIssue[]
  updated_at: string
}

// Mirror of GET /rules (see server/rules.py)
interface Rules {
  mainDeckSize: number
  mainDeckUnits: number
  mainDeckNonUnits: number
  rarityCopyLimits: Record<string, number | null>
  celestialDeckLimit: number
  reserveSlots: Record<string, number>
  reserveSlotsCasual: Record<string, number>
  openDesignations: string[]
}

// -- Card helpers
const STAGE_SUFFIX = /\s*\((Base|Evol\. 1|Evol\. 2)\)$/
const NON_UNIT_TYPES: CardType[] = ["Spell", "Ability", "Core"]
const RESERVE_ORDER = ["Weapon", "Armor", "Battlefield", "Feat"]

const displayName = (card: ApiCard) => card.id.replace(STAGE_SUFFIX, "")
const isUnit = (card: ApiCard) => card.card_type === "Unit"
const isNonUnit = (card: ApiCard) => NON_UNIT_TYPES.includes(card.card_type)
const isReserve = (card: ApiCard) => card.card_type === "Reserve"
const isBaseCommander = (card: ApiCard) => card.card_type === "Commander" && card.attributes[1] === "Base"
const reserveType = (card: ApiCard) => (isReserve(card) ? card.attributes[1] ?? "?" : null)
const isCelestialCard = (card: ApiCard) => card.rarity === "Celestial" || card.faction === "Celestial"
const imagePath = (card: ApiCard | undefined) => card?.printings.find(p => p.image)?.image ?? null

const FACTION_COLORS: Record<string, string> = {
  Celestial: "#8ec9e8",
  Draconian: "#e07a3f",
  Druidian: "#7aa85c",
  Mercenary: "#b08d57",
  Necromancer: "#9a6fc9",
  Universal: "#a8a29e",
  Valkyrian: "#d4af5a",
  Vampyrian: "#c04545",
  Wolven: "#7d93a8",
}

const RARITY_COLORS: Record<string, string> = {
  Common: "#caa872",
  Uncommon: "#a9d161",
  Rare: "#6aaad7",
  Epic: "#aa72da",
  Legendary: "#d85f5a",
  Celestial: "#e8ecf2",
}

const factionColor = (faction: string) => FACTION_COLORS[faction] ?? "#a8a29e"
const rarityColor = (rarity: string | null) => (rarity && RARITY_COLORS[rarity]) ?? "#a8a29e"

const isFactionLegal = (commander: ApiCard, card: ApiCard, rules: Rules) =>
  card.faction === commander.faction ||
  rules.openDesignations.includes(card.faction) ||
  card.rarity === "Celestial"

// Legal to ever include with this commander (drives the typeahead pool);
// quantity limits are enforced per-line instead.
const isSelectable = (commander: ApiCard | undefined, card: ApiCard, rules: Rules) => {
  if (card.card_type === "Commander" || card.card_type === "Token") return false
  if (!commander) return true
  if (card.specialization && card.specialization !== displayName(commander)) return false
  return isReserve(card) || isFactionLegal(commander, card, rules)
}

const rarityLimit = (card: ApiCard, rules: Rules) => {
  const limit = card.rarity ? rules.rarityCopyLimits[card.rarity] : null
  return limit ?? Infinity
}

// The most copies you'd usually want in one go: the rarity's copy limit, with
// unlimited rarities (Common) settling at a playset. Reserve cards are unique.
const DEFAULT_QTY = 3
const defaultQty = (card: ApiCard, rules: Rules) =>
  isReserve(card) ? 1 : Math.min(rarityLimit(card, rules), DEFAULT_QTY)

// Decklist text: parse/serialize the editor textarea format
interface Line {
  count: number
  name: string // as typed; the canonical id when resolved
  card: ApiCard | null
}

const SECTIONS = ["commander", "main deck", "reserve deck", "resource deck"]
const COUNT_RE = /^(\d+)\s*x?\s+(.+)$/i

const lineKey = (line: Line) => line.card?.id ?? line.name.toLowerCase()

const resolveCard = (name: string, byLower: Map<string, ApiCard>) =>
  byLower.get(name.toLowerCase()) ?? byLower.get(`${name.toLowerCase()} (base)`) ?? null

const mergeLine = (lines: Line[], line: Line): Line[] => {
  const existing = lines.find(l => lineKey(l) === lineKey(line))
  if (!existing) return [...lines, line]
  return lines.map(l => (l === existing ? { ...l, count: l.count + line.count } : l))
}

interface ParsedText {
  name?: string
  commanderId?: string
  main: Line[]
  reserve: Line[]
}

const parseDeckText = (text: string, byLower: Map<string, ApiCard>): ParsedText => {
  const out: ParsedText = { main: [], reserve: [] }
  let section = "main deck"
  for (const raw of text.split("\n")) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith("#")) {
      const name = line.replace(/^#+/, "").trim()
      if (name) out.name = name
      continue
    }
    const header = line.replace(/:$/, "").toLowerCase()
    if (line.endsWith(":") && SECTIONS.includes(header)) {
      section = header
      continue
    }
    if (section === "resource deck") continue // derived from the commander
    const match = COUNT_RE.exec(line)
    const count = match ? parseInt(match[1], 10) : 1
    const name = (match ? match[2] : line).trim()
    if (count < 1) continue
    const card = resolveCard(name, byLower)
    if (section === "commander") {
      if (card) out.commanderId = card.id
      continue
    }
    const entry: Line = { count, name: card ? card.id : name, card }
    if (section === "reserve deck") out.reserve = mergeLine(out.reserve, entry)
    else out.main = mergeLine(out.main, entry)
  }
  return out
}

const lineText = (line: Line) => `${line.count}x ${line.name}`

// The textarea holds only the card lines (commander and name have their own
// inputs), but parseDeckText still accepts full exports pasted in.
const draftText = (main: Line[], reserve: Line[]) => {
  const parts = main.map(lineText)
  if (reserve.length > 0) parts.push("", "Reserve Deck:", ...reserve.map(lineText))
  return parts.join("\n")
}

// Deck counting & per-line legality
interface DeckCounts {
  units: number
  nonUnits: number
  cores: number
  mercenaries: number
  celestials: number
  copies: Record<string, number>
  reserveByType: Record<string, number>
  reserveTotal: number
}

const countDeck = (main: Line[], reserve: Line[]): DeckCounts => {
  const counts: DeckCounts = {
    units: 0,
    nonUnits: 0,
    cores: 0,
    mercenaries: 0,
    celestials: 0,
    copies: {},
    reserveByType: {},
    reserveTotal: 0,
  }
  for (const { card, count } of main) {
    if (!card) continue
    if (isUnit(card)) counts.units += count
    if (isNonUnit(card)) counts.nonUnits += count
    if (card.card_type === "Core") counts.cores += count
    if (card.faction === "Mercenary") counts.mercenaries += count
    if (isCelestialCard(card)) counts.celestials += count
    counts.copies[card.id] = (counts.copies[card.id] ?? 0) + count
  }
  for (const { card, count } of reserve) {
    if (!card) continue
    const type = reserveType(card) ?? "?"
    counts.reserveByType[type] = (counts.reserveByType[type] ?? 0) + count
    counts.reserveTotal += count
    if (isCelestialCard(card)) counts.celestials += count
  }
  return counts
}

// Why this line is illegal as it stands; null means it's fine. Mirrors
// server/validation.py closely enough to color lines red while typing.
const lineIssue = (
  line: Line,
  zone: "main" | "reserve",
  commander: ApiCard | undefined,
  counts: DeckCounts,
  casual: boolean,
  rules: Rules,
): string | null => {
  const { card } = line
  if (!card) return "Unknown card"
  if (zone === "main") {
    if (isReserve(card)) return "Reserve cards go in the Reserve Deck"
    if (!isUnit(card) && !isNonUnit(card)) return `${card.card_type} cards can't be in the main deck`
    if (commander) {
      if (card.specialization && card.specialization !== displayName(commander))
        return `Only legal with ${card.specialization}`
      if (!isFactionLegal(commander, card, rules))
        return `${card.faction} cards aren't legal in a ${commander.faction} deck`
    }
    const limit = rarityLimit(card, rules)
    if (line.count > limit)
      return `${card.rarity}: maximum ${limit} ${limit === 1 ? "copy" : "copies"} per deck`
    if (isCelestialCard(card) && counts.celestials > rules.celestialDeckLimit)
      return `Maximum ${rules.celestialDeckLimit} Celestial card in the whole deck`
    return null
  }
  if (!isReserve(card)) return "Only Weapon, Armor, Battlefield and Feat cards go in the Reserve Deck"
  if (commander && card.specialization && card.specialization !== displayName(commander))
    return `Only legal with ${card.specialization}`
  if (line.count > 1) return "Each Reserve card must be unique"
  const slots = casual ? rules.reserveSlotsCasual : rules.reserveSlots
  const type = reserveType(card) ?? "?"
  if ((counts.reserveByType[type] ?? 0) > (slots[type] ?? 0))
    return `Too many ${type} cards (${slots[type] ?? 0} slot${(slots[type] ?? 0) === 1 ? "" : "s"})`
  if (isCelestialCard(card) && counts.celestials > rules.celestialDeckLimit)
    return `Maximum ${rules.celestialDeckLimit} Celestial card in the whole deck`
  return null
}

// API client
const request = async <T,>(path: string, token?: string | null, init?: RequestInit): Promise<T> => {
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    const detail = await res.json().then(body => body.detail).catch(() => null)
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`)
  }
  return res.json()
}

// Editor draft
interface Draft {
  id: string | null
  name: string
  commanderId: string
  main: Line[]
  reserve: Line[]
  casual: boolean
}

const collate = (entries: DeckEntry[], byId: Map<string, ApiCard>): Line[] =>
  entries.map(e => ({ count: e.count, name: e.card_id, card: byId.get(e.card_id) ?? null }))

const collateReserve = (ids: string[], byId: Map<string, ApiCard>): Line[] =>
  ids.reduce<Line[]>(
    (lines, id) => mergeLine(lines, { count: 1, name: id, card: byId.get(id) ?? null }),
    [],
  )

const deckToDraft = (deck: SavedDeck, byId: Map<string, ApiCard>): Draft => ({
  id: deck.id,
  name: deck.name,
  commanderId: deck.commander_id,
  main: collate(deck.main_deck, byId),
  reserve: collateReserve(deck.reserve_deck, byId),
  casual: deck.casual,
})

const draftPayload = (draft: Draft): DeckPayload => ({
  name: draft.name.trim() || "Untitled deck",
  commander_id: draft.commanderId,
  main_deck: draft.main
    .filter(l => l.card !== null)
    .map(l => ({ card_id: l.card!.id, count: l.count })),
  reserve_deck: draft.reserve.flatMap(l => (l.card ? Array<string>(l.count).fill(l.card.id) : [])),
  casual: draft.casual,
})

const BTN_DANGER =
  "px-3 py-0.5 rounded border border-red-950/80 bg-gradient-to-b from-red-700 to-red-900 " +
  "text-white shadow-sm whitespace-nowrap enabled:cursor-pointer " +
  "enabled:hover:from-red-600 enabled:hover:to-red-800 disabled:opacity-40"
const PANE_HEAD = "text-base font-bold mt-3 mb-1"

// Small pieces

// Text-rendered proxy for the hover zoom when a card has no scanned image.
const CardProxy: React.FC<{ card: ApiCard }> = ({ card }) => (
  <div className="aspect-[63/88] w-full flex flex-col rounded-lg border bg-navy-900 overflow-hidden shadow-2xl">
    <div className="px-3 pt-2.5 pb-1.5 border-b">
      <div className="flex items-start justify-between gap-1.5">
        <div className="font-semibold leading-tight">{displayName(card)}</div>
        {card.cost != null && (
          <div className="shrink-0 w-6 h-6 rounded-full border flex items-center justify-center">
            {card.cost}
          </div>
        )}
      </div>
      <div className="text-xs uppercase tracking-wider truncate" style={{ color: factionColor(card.faction) }}>
        {card.faction} · {card.attributes.length > 0 ? card.attributes.join(" - ") : card.card_type}
      </div>
    </div>
    <div className="grow min-h-0 px-3 py-2 leading-snug text-gray-200 whitespace-pre-line overflow-hidden">
      {card.rules_text.replace(/\r/g, "")}
    </div>
    <div className="px-3 py-1.5 border-t flex items-center justify-between text-xs">
      <span className="flex gap-2 text-gray-300">
        {card.attack != null && <span>ATK {card.attack}</span>}
        {card.shield_capacity != null && <span>SHD {card.shield_capacity}</span>}
        {(card.health ?? card.hp) != null && <span>HP {card.health ?? card.hp}</span>}
      </span>
      <span style={{ color: rarityColor(card.rarity) }}>{card.rarity}</span>
    </div>
  </div>
)

const ZOOM_WIDTH = 320 // w-80
const ZOOM_HEIGHT = ZOOM_WIDTH * (88 / 63) // matches the aspect-[63/88] card art
const ZOOM_MARGIN = 16

const ZoomCard: React.FC<{ card: ApiCard; x: number; y: number }> = ({ card, x, y }) => {
  // Seeded with the triggering hover's position, then tracks the cursor directly
  // so re-renders stay local to this component instead of the whole tree.
  const [pos, setPos] = useState({ x, y })
  useEffect(() => {
    const onMove = (e: MouseEvent) => setPos({ x: e.clientX, y: e.clientY })
    window.addEventListener("mousemove", onMove)
    return () => window.removeEventListener("mousemove", onMove)
  }, [])

  const overflowsRight = pos.x + ZOOM_MARGIN + ZOOM_WIDTH > window.innerWidth
  const left = overflowsRight ? pos.x - ZOOM_MARGIN - ZOOM_WIDTH : pos.x + ZOOM_MARGIN
  const top = Math.min(pos.y + ZOOM_MARGIN, window.innerHeight - ZOOM_HEIGHT - ZOOM_MARGIN)

  const image = imagePath(card)
  return (
    <div className="pointer-events-none fixed z-40 w-80" style={{ left, top: Math.max(top, ZOOM_MARGIN) }}>
      {image
        ? <img className="w-full rounded-lg shadow-2xl" src={image} alt={card.id} />
        : <CardProxy card={card} />}
    </div>
  )
}

// Left panel: deck collection
const DeckThumb: React.FC<{ commander: ApiCard | undefined; fallback: string }> = (
  { commander, fallback },
) => {
  const image = imagePath(commander)
  if (image) {
    return <img className="w-12 h-12 shrink-0 rounded object-cover object-top" src={image} alt="" />
  }
  const faction = commander?.faction
  return (
    <div
      className="w-12 h-12 shrink-0 rounded flex items-center justify-center text-xl font-bold text-black/60"
      style={{ backgroundColor: faction ? factionColor(faction) : "#556" }}
    >
      {(commander ? displayName(commander) : fallback).slice(0, 1)}
    </div>
  )
}

interface DecksPanelProps {
  token?: string | null
  decks: SavedDeck[]
  decksStatus: "loading" | "error" | "ready"
  byId: Map<string, ApiCard>
  selectedId: string | null
  editing: boolean
  onSelect: (deck: SavedDeck) => void
  onNew: () => void
}

const DecksPanel: React.FC<DecksPanelProps> = ({ token, decks, decksStatus, byId, selectedId, editing, onSelect, onNew }) => {
  const shown = useMemo(
    () => [...decks].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
    [decks],
  )

  return (
    <div className="h-full flex flex-col min-h-0 p-3">
      <div className="shrink-0 flex flex-wrap gap-2">
        <button disabled={!token || editing} onClick={onNew}>New deck</button>
      </div>
      <h3 className="my-3">
        {decksStatus === "ready" && `${shown.length} Deck${shown.length === 1 ? "" : "s"}`}
      </h3>
      <div className="grow">
        {!token && <div className="p-3 text-gray-400">Sign in to load and save your decks.</div>}
        {token && decksStatus === "loading" && <div className="p-3">Loading deck collection…</div>}
        {token && decksStatus === "error" &&
          <div className="p-3 text-red-400">
            Couldn't load your decks. Check that the deckbuilder server is running, then reload.
          </div>}
        {token && decksStatus === "ready" && shown.length === 0 &&
          <div className="p-3 text-gray-400">No decks yet — create one.</div>}
        {token && decksStatus === "ready" && shown.map(deck => {
          const commander = byId.get(deck.commander_id)
          const active = deck.id === selectedId
          return (
            <div
              key={deck.id}
              className={`w-full flex items-start gap-3 text-left rounded-lg border p-3 mb-1.5 cursor-pointer ${active ? "active" : ""}`}
              onClick={() => onSelect(deck)}
            >
              <DeckThumb commander={commander} fallback={deck.commander_id} />
              <span className="grow min-w-0">
                <span className="block truncate font-semibold">{deck.name}</span>
                <span className="block truncate">
                  {commander ?
                    <span style={{ color: factionColor(commander.faction) }}>{displayName(commander)}</span>
                    : deck.commander_id}
                </span>
              </span>
              <div className="shrink-0 text-right">
                {deck.casual && "Casual"}
                <span className="block">
                  {new Date(deck.updated_at).toLocaleDateString()}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// Middle panel: the selected decklist
interface ShownDeck {
  name: string
  commanderId: string
  main: Line[]
  reserve: Line[]
  casual: boolean
  issues: ValidationIssue[] | null
}

interface DecklistPanelProps {
  shown: ShownDeck | null
  mode: "view" | "edit" | "delete"
  token?: string | null
  byId: Map<string, ApiCard>
  rules: Rules
  saving: boolean
  notice: { error: boolean; text: string } | null
  onEdit: () => void
  onDelete: () => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
  onSave: () => void
  onCancelEdit: () => void
  onBump: (zone: "main" | "reserve", key: string, delta: number) => void
  onZoom: (card: ApiCard | null, e?: React.MouseEvent) => void
}

const DecklistPanel: React.FC<DecklistPanelProps> = ({
  shown, mode, token, byId, rules, saving, notice, onEdit, onDelete,
  onConfirmDelete, onCancelDelete, onSave, onCancelEdit, onBump, onZoom,
}) => {
  if (!shown) {
    return (
      <div className="h-full flex items-center justify-center">
        Select a deck, or create a new one.
      </div>
    )
  }

  const commander = byId.get(shown.commanderId)
  const counts = countDeck(shown.main, shown.reserve)
  const reserveSlots = shown.casual ? rules.reserveSlotsCasual : rules.reserveSlots
  const reserveRequired = Object.values(reserveSlots).reduce((sum, n) => sum + n, 0)
  const editing = mode === "edit"

  const buttonBar = mode === "delete" ? (
      <div className="flex flex-wrap items-center gap-2">
        <button className={BTN_DANGER} onClick={onConfirmDelete}>Confirm Delete</button>
        <button onClick={onCancelDelete}>Cancel</button>
        <span className="text-red-400">This cannot be undone.</span>
      </div>
    )
    : editing ? (
        <div className="flex flex-wrap items-center gap-2">
          <button disabled={!token || !commander || saving} onClick={onSave}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button onClick={onCancelEdit}>Cancel</button>
          {!token && <span className="text-gray-400">Sign in to save decks</span>}
        </div>
      )
      : (
        <div className="flex flex-wrap items-center gap-2">
          <button disabled={!token} onClick={onEdit}>Edit</button>
          <button disabled={!token} onClick={onDelete}>Delete</button>
        </div>
      )

  const num = (value: number, target: number, exact = true) => (
    <span className={value > target || (exact && value < target) ? "text-red-400" : ""}>
      {value}
    </span>
  )

  const group = (title: string, zone: "main" | "reserve", lines: Line[]) => {
    if (lines.length === 0) return null
    const total = lines.reduce((sum, l) => sum + l.count, 0)
    return (
      <div key={`${zone}-${title}`} className="break-inside-avoid mb-3">
        <h4 className="font-bold">{title} ({total})</h4>
        {lines.map(line => {
          const issue = lineIssue(line, zone, commander, counts, shown.casual, rules)
          return (
            <div key={lineKey(line)} className="flex items-center gap-1.5 leading-6">
              {editing && (
                <span className="flex gap-0.5">
                  <button
                    className="w-5 h-5 flex items-center justify-center rounded border bg-navy-900/80 cursor-pointer hover:bg-sky-900/50"
                    aria-label={`Remove one ${line.name}`}
                    onClick={() => onBump(zone, lineKey(line), -1)}
                  >
                    −
                  </button>
                  <button
                    className="w-5 h-5 flex items-center justify-center rounded border bg-navy-900/80 cursor-pointer hover:bg-sky-900/50"
                    aria-label={`Add one ${line.name}`}
                    onClick={() => onBump(zone, lineKey(line), 1)}
                  >
                    +
                  </button>
                </span>
              )}
              <span>{line.count}</span>
              <span
                className={`text-primary truncate ${issue ? "text-red-400" : ""}`}
                onMouseEnter={e => line.card && onZoom(line.card, e)}
                onMouseLeave={() => onZoom(null)}
              >
                {line.card ? displayName(line.card) : line.name}
              </span>
            </div>
          )
        })}
      </div>
    )
  }

  const mainGroups: [string, (line: Line) => boolean][] = [
    ["Units", l => l.card !== null && isUnit(l.card)],
    ["Spells", l => l.card?.card_type === "Spell"],
    ["Abilities", l => l.card?.card_type === "Ability"],
    ["Artifact Cores", l => l.card?.card_type === "Core"],
    ["Other", l => l.card === null || isReserve(l.card) || (!isUnit(l.card) && !isNonUnit(l.card))]
  ]

  return (
    <div className="h-full flex flex-col min-h-0 p-3">
      <div className="shrink-0 flex flex-wrap items-center gap-2">
        {buttonBar}
        {notice && <span className={notice.error ? "text-red-400" : ""}>{notice.text}</span>}
      </div>
      <h3 className="shrink-0 my-3 text-xl font-bold truncate">{shown.name}</h3>
      <div className="shrink-0 mt-2 flex gap-3">
        {commander && imagePath(commander) ?
          <img
            className="w-20 h-28 shrink-0 rounded object-cover cursor-zoom-in"
            src={imagePath(commander)!}
            alt={displayName(commander)}
            onMouseEnter={e => onZoom(commander, e)}
            onMouseLeave={() => onZoom(null)}
          />
          : <DeckThumb commander={commander} fallback={shown.commanderId || "?"} />}
        <div className="min-w-0 leading-6">
          {commander ?
            <div
              className="text-primary font-semibold text-base truncate"
              onMouseEnter={e => onZoom(commander, e)}
              onMouseLeave={() => onZoom(null)}
            >
              {displayName(commander)}
            </div> :
            <div className="font-semibold text-red-400">
              {shown.commanderId ? `Unknown commander: ${shown.commanderId}` : "No commander chosen"}
            </div>}
          <div>
            {num(counts.units + counts.nonUnits, rules.mainDeckSize)}/{rules.mainDeckSize} {" "} Cards ·
            Units {num(counts.units, rules.mainDeckUnits)}/{rules.mainDeckUnits} · Non-units{" "}
            {num(counts.nonUnits, rules.mainDeckNonUnits)}/{rules.mainDeckNonUnits} · Reserve{" "}
            {num(counts.reserveTotal, reserveRequired)}/{reserveRequired}
          </div>
          {commander &&
            <div>
              Cores {num(counts.cores, commander.core_energy ?? 0)}/{commander.core_energy ?? 0}
              {" · "}Mercenaries{" "}
              <span className={counts.mercenaries > (commander.mercenary_limit ?? 0) ? "text-red-400" : ""}>
                {counts.mercenaries}
              </span>/{commander.mercenary_limit ?? 0}
              {" · "}Celestial{" "}
              <span className={counts.celestials > rules.celestialDeckLimit ? "text-red-400" : ""}>
                {counts.celestials}
              </span>/{rules.celestialDeckLimit}
            </div>}
        </div>
      </div>
      <div className="grow overflow-auto mt-3 pt-3">
        <div className="columns-2 gap-x-6">
          {mainGroups.map(([title, test], index) => {
            // Each line lands in its first matching group
            const taken = mainGroups.slice(0, index).map(([, t]) => t)
            const lines = shown.main
              .filter(l => test(l) && !taken.some(t => t(l)))
              .sort((a, b) =>
                (a.card?.cost ?? 99) - (b.card?.cost ?? 99) || a.name.localeCompare(b.name))
            return group(title, "main", lines)
          })}
          {group(
            "Reserve",
            "reserve",
            [...shown.reserve].sort((a, b) =>
              RESERVE_ORDER.indexOf(reserveType(a.card ?? ({} as ApiCard)) ?? "")
                - RESERVE_ORDER.indexOf(reserveType(b.card ?? ({} as ApiCard)) ?? "")
              || a.name.localeCompare(b.name)),
          )}
        </div>
      </div>
    </div>
  )
}

// Right panel: edit form
const CardLookup: React.FC<{
  cards: ApiCard[]
  commander: ApiCard | undefined
  rules: Rules
  onAdd: (card: ApiCard, qty: number) => void
}> = ({ cards, commander, rules, onAdd }) => {
  const [query, setQuery] = useState("")
  const [qty, setQty] = useState(String(DEFAULT_QTY))
  const [selected, setSelected] = useState(0)
  const queryRef = useRef<HTMLInputElement | null>(null)
  const qtyRef = useRef<HTMLInputElement | null>(null)

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return cards
      .filter(card => isSelectable(commander, card, rules) &&
        displayName(card).toLowerCase().includes(q))
      .sort((a, b) => {
        const aName = displayName(a).toLowerCase()
        const bName = displayName(b).toLowerCase()
        return Number(bName.startsWith(q)) - Number(aName.startsWith(q)) ||
          aName.localeCompare(bName)
      })
      .slice(0, 10)
  }, [cards, commander, rules, query])

  const pick = matches[Math.min(selected, Math.max(matches.length - 1, 0))]
  const exact = pick != null && displayName(pick).toLowerCase() === query.trim().toLowerCase()

  // Picking a card fills the name and hands over to the quantity box, primed
  // with the most copies of that card the deck can hold.
  const choose = (card: ApiCard, index: number) => {
    setQuery(displayName(card))
    setQty(String(defaultQty(card, rules)))
    setSelected(index)
    qtyRef.current?.select()
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!pick) return
    const parsed = parseInt(qty, 10)
    onAdd(pick, Number.isNaN(parsed) ? 1 : Math.max(parsed, 1))
    setQuery("")
    setQty(String(DEFAULT_QTY))
    setSelected(0)
    queryRef.current?.focus()
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowUp") {
      e.preventDefault()
      setSelected(i => Math.max(i - 1, 0))
    } else if (e.key === "ArrowDown") {
      e.preventDefault()
      setSelected(i => Math.min(i + 1, matches.length - 1))
    } else if ((e.key === "Enter" || e.key === "Tab") && pick && !exact) {
      e.preventDefault()
      choose(pick, matches.indexOf(pick))
    }
  }

  return (
    <form className="relative" onSubmit={submit}>
      <div className="flex items-center gap-2">
        <input
          ref={queryRef}
          className="grow min-w-0"
          placeholder="Card name"
          aria-label="Card name"
          value={query}
          onChange={e => {
            setQuery(e.target.value)
            setSelected(0)
          }}
          onKeyDown={onKeyDown}
        />
        <span className="text-gray-400">×</span>
        <input
          ref={qtyRef}
          className="w-12 text-center"
          aria-label="Quantity"
          value={qty}
          onChange={e => setQty(e.target.value)}
        />
        <button type="submit" disabled={!pick}>Add to deck</button>
      </div>
      {query.trim() && matches.length > 0 && !exact && (
        <div className="absolute left-0 right-28 top-full z-30 mt-1 rounded border bg-navy-900 shadow-xl">
          {matches.map((card, i) => (
            <div
              key={card.id}
              className={`px-2 py-1 cursor-pointer ${i === selected ? "bg-sky-800/70" : "hover:bg-sky-900/50"}`}
              onMouseDown={e => {
                e.preventDefault()
                choose(card, i)
              }}
            >
              {displayName(card)}
              <span className="ml-2 text-gray-400">
                {card.card_type}
                {isReserve(card) && ` · ${reserveType(card)}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </form>
  )
}

interface EditPanelProps {
  draft: Draft | null
  text: string
  cards: ApiCard[]
  byId: Map<string, ApiCard>
  rules: Rules
  nameRef: React.RefObject<HTMLInputElement | null>
  onDraft: (draft: Draft) => void
  onText: (text: string) => void
  onAdd: (card: ApiCard, qty: number) => void
}

const EditPanel: React.FC<EditPanelProps> = ({ draft, text, cards, byId, rules, nameRef, onDraft, onText, onAdd }) => {
  const commanders = useMemo(
    () =>
      cards
        .filter(isBaseCommander)
        .sort((a, b) => a.faction.localeCompare(b.faction) || a.id.localeCompare(b.id)),
    [cards],
  )

  if (!draft) return <div className="h-full" />
  const commander = byId.get(draft.commanderId)

  return (
    <div className="h-full flex flex-col min-h-0 p-3 overflow-auto">
      <h3 className={PANE_HEAD}>Deck name</h3>
      <input
        ref={nameRef}
        className="w-full"
        value={draft.name}
        maxLength={100}
        aria-label="Deck name"
        onChange={e => onDraft({ ...draft, name: e.target.value })}
      />
      <h3 className={PANE_HEAD}>Commander</h3>
      <select
        className="w-full cursor-pointer"
        value={draft.commanderId}
        aria-label="Commander"
        onChange={e => onDraft({ ...draft, commanderId: e.target.value })}
      >
        {!commander &&
          <option value={draft.commanderId}>
            {draft.commanderId ? `Unknown: ${draft.commanderId}` : "Choose a commander"}
          </option>}
        {commanders.map(card =>
          <option key={card.id} value={card.id}>
            {card.faction} — {displayName(card)}
          </option>)}
      </select>
      <div className="mt-2 flex gap-4">
        <label className="flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            className="accent-sky-500"
            checked={draft.casual}
            onChange={e => onDraft({ ...draft, casual: e.target.checked })}
          />
          Casual (5-card reserve)
        </label>
      </div>
      <h3 className={PANE_HEAD}>Add cards</h3>
      <CardLookup cards={cards} commander={commander} rules={rules} onAdd={onAdd} />
      <h3 className={PANE_HEAD}>
        Decklist{" "}
        <span className="font-normal text-gray-400 text-sm">
          (Type or paste a deck list, it will be parsed)
        </span>
      </h3>
      <textarea
        className="w-full grow min-h-48 font-mono resize-none"
        aria-label="Decklist"
        value={text}
        onChange={e => onText(e.target.value)}
      />
    </div>
  )
}

// Root
interface DeckBuilderProps {
  token?: string | null
}

const DeckBuilder: React.FC<DeckBuilderProps> = ({ token }) => {
  const [rules, setRules] = useState<Rules | null>(null)
  const [cards, setCards] = useState<ApiCard[]>([])
  const [loadStatus, setLoadStatus] = useState<"loading" | "error" | "ready">("loading")
  const [decks, setDecks] = useState<SavedDeck[]>([])
  const [decksStatus, setDecksStatus] = useState<"loading" | "error" | "ready">("loading")
  const [selected, setSelected] = useState<SavedDeck | null>(null)
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view")
  const [draft, setDraft] = useState<Draft | null>(null)
  const [text, setText] = useState("")
  const [liveIssues, setLiveIssues] = useState<ValidationIssue[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<{ error: boolean; text: string } | null>(null)
  const [zoom, setZoom] = useState<{ card: ApiCard; x: number; y: number } | null>(null)
  const onZoom = (card: ApiCard | null, e?: React.MouseEvent) =>
    setZoom(card && e ? { card, x: e.clientX, y: e.clientY } : null)
  const nameRef = useRef<HTMLInputElement | null>(null)
  const byId = useMemo(() => new Map(cards.map(card => [card.id, card])), [cards])
  const byLower = useMemo(() => new Map(cards.map(card => [card.id.toLowerCase(), card])), [cards])

  useEffect(() => {
    setLoadStatus("loading")
    Promise.all([request<Rules>("/rules"), request<ApiCard[]>("/cards")])
      .then(([rulesData, cardData]) => {
        setRules(rulesData)
        setCards(cardData)
        setLoadStatus("ready")
      })
      .catch(() => setLoadStatus("error"))
  }, [])

  const loadDecks = (select?: SavedDeck | null) => {
    if (!token) {
      setDecksStatus("ready")
      return
    }
    request<SavedDeck[]>("/decks", token)
      .then(list => {
        setDecks(list)
        setDecksStatus("ready")
        if (select !== undefined) setSelected(select)
      })
      .catch(() => setDecksStatus("error"))
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(loadDecks, [token])

  // Live rules check against the server's authoritative validation engine.
  const payloadJson = draft && mode === "edit" ? JSON.stringify(draftPayload(draft)) : null
  useEffect(() => {
    if (!payloadJson) return
    let stale = false
    const timer = setTimeout(() => {
      request<ValidationIssue[]>("/decks/validate", token, { method: "POST", body: payloadJson })
        .then(issues => !stale && setLiveIssues(issues))
        .catch(() => {})
    }, 400)
    return () => {
      stale = true
      clearTimeout(timer)
    }
  }, [payloadJson, token])

  const flash = (error: boolean, message: string) => setNotice({ error, text: message })

  const startEdit = (base: Draft) => {
    setDraft(base)
    setText(draftText(base.main, base.reserve))
    setLiveIssues(null)
    setNotice(null)
    setMode("edit")
    setTimeout(() => nameRef.current?.select(), 500) // after the slide
  }

  const firstCommander = useMemo(() => cards.filter(isBaseCommander).sort((a, b) => a.id.localeCompare(b.id))[0], [cards])

  const onNew = () =>
    startEdit({
      id: null,
      name: "New deck",
      commanderId: firstCommander?.id ?? "",
      main: [],
      reserve: [],
      casual: false,
    })

  const onEdit = () => selected && startEdit(deckToDraft(selected, byId))

  const onCancelEdit = () => {
    setMode("view")
    setDraft(null)
    setNotice(null)
  }

  const onDraftChange = (next: Draft) => setDraft(next)

  const onTextChange = (nextText: string) => {
    setText(nextText)
    if (!draft) return
    const parsed = parseDeckText(nextText, byLower)
    setDraft({
      ...draft,
      main: parsed.main,
      reserve: parsed.reserve,
      ...(parsed.name ? { name: parsed.name } : {}),
      ...(parsed.commanderId ? { commanderId: parsed.commanderId } : {}),
    })
  }

  const applyDraft = (next: Draft) => {
    setDraft(next)
    setText(draftText(next.main, next.reserve))
  }

  const onBump = (zone: "main" | "reserve", key: string, delta: number) => {
    if (!draft) return
    const lines = draft[zone]
      .map(line => (lineKey(line) === key ? { ...line, count: line.count + delta } : line))
      .filter(line => line.count > 0)
    applyDraft({ ...draft, [zone]: lines })
  }

  const onAdd = (card: ApiCard, qty: number) => {
    if (!draft || !rules) return
    if (isReserve(card)) {
      if (draft.reserve.some(l => lineKey(l) === card.id)) return
      applyDraft({ ...draft, reserve: [...draft.reserve, { count: 1, name: card.id, card }] })
      return
    }
    const existing = draft.main.find(l => lineKey(l) === card.id)
    const capped = Math.min((existing?.count ?? 0) + qty, rarityLimit(card, rules))
    if (existing && capped <= existing.count) return
    const main = existing
      ? draft.main.map(l => (l === existing ? { ...l, count: capped } : l))
      : [...draft.main, { count: capped, name: card.id, card }]
    applyDraft({ ...draft, main })
  }

  const onSave = async () => {
    if (!draft) return
    setSaving(true)
    setNotice(null)
    try {
      const body = JSON.stringify(draftPayload(draft))
      const saved = draft.id
        ? await request<SavedDeck>(`/decks/${draft.id}`, token, { method: "PUT", body })
        : await request<SavedDeck>("/decks", token, { method: "POST", body })
      loadDecks(saved)
      setMode("view")
      setDraft(null)
      flash(false, saved.is_valid ? "Saved — deck is legal" : "Saved with issues")
    } catch (err) {
      flash(true, err instanceof Error ? err.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  const onConfirmDelete = async () => {
    if (!selected) return
    try {
      await request(`/decks/${selected.id}`, token, { method: "DELETE" })
      setMode("view")
      loadDecks(null)
    } catch (err) {
      setMode("view")
      flash(true, err instanceof Error ? err.message : "Delete failed")
    }
  }

  const shown: ShownDeck | null = mode === "edit" && draft
    ? {
      name: draft.name,
      commanderId: draft.commanderId,
      main: draft.main,
      reserve: draft.reserve,
      casual: draft.casual,
      issues: liveIssues,
    }
    : selected
      ? {
        name: selected.name,
        commanderId: selected.commander_id,
        main: collate(selected.main_deck, byId),
        reserve: collateReserve(selected.reserve_deck, byId),
        casual: selected.casual,
        issues: selected.issues,
      }
      : null

  if (loadStatus !== "ready" || !rules) {
    return (
      <div className="grow h-full flex items-center justify-center p-3">
        {loadStatus === "error" ?
          "Couldn't reach the deckbuilder server. Check that it's running, then reload."
          : "Loading cards…"}
      </div>
    )
  }

  const editing = mode === "edit"

  return (
    // h-full, not just grow: the host mounts this in a plain block container
    // (fireball's .body), where flex-grow does nothing and the panels' h-full
    // would have no definite height to resolve against.
    <div className="h-full relative min-h-0 p-3">
      <div className="h-full rounded-lg overflow-hidden pane max-w-[1120px] mx-auto">
        {/* Sliding viewport: 150% wide, so each of the three panels is half the
            pane, and editing slides the deck collection out to the left. */}
        <div
          className="h-full flex transition-transform duration-500 ease-in-out"
          style={{ width: "150%", transform: editing ? "translateX(-33.3333%)" : undefined }}
        >
          <section
            style={{ width: "33.3333%" }}
            className="h-full shrink-0 border-r"
            aria-label="Deck collection"
          >
            <DecksPanel
              token={token}
              decks={decks}
              decksStatus={decksStatus}
              byId={byId}
              selectedId={selected?.id ?? null}
              editing={editing}
              onSelect={deck => {
                if (editing) return
                setSelected(deck)
                setMode("view")
                setNotice(null)
              }}
              onNew={onNew}
            />
          </section>
          <section
            style={{ width: "33.3333%" }}
            className="h-full shrink-0"
            aria-label="Decklist"
          >
            <DecklistPanel
              shown={shown}
              mode={mode}
              token={token}
              byId={byId}
              rules={rules}
              saving={saving}
              notice={notice}
              onEdit={onEdit}
              onDelete={() => setMode("delete")}
              onConfirmDelete={onConfirmDelete}
              onCancelDelete={() => setMode("view")}
              onSave={onSave}
              onCancelEdit={onCancelEdit}
              onBump={onBump}
              onZoom={onZoom}
            />
          </section>
          <section
            style={{ width: "33.3333%" }}
            className="h-full shrink-0 border-l"
            aria-label="Deck editor"
          >
            <EditPanel
              draft={draft}
              text={text}
              cards={cards}
              byId={byId}
              rules={rules}
              nameRef={nameRef}
              onDraft={onDraftChange}
              onText={onTextChange}
              onAdd={onAdd}
            />
          </section>
        </div>
      </div>
      {zoom && <ZoomCard card={zoom.card} x={zoom.x} y={zoom.y} />}
    </div>
  )
}

export default DeckBuilder
