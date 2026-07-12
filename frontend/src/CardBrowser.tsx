import React, { useEffect, useMemo, useState } from "react"
import { FiSearch } from "react-icons/fi"
import type { Card, Printing } from "./interfaces"

interface FilterSelectProps {
  label: string
  value: string
  options: string[]
  allLabel?: string
  onChange: (value: string) => void
}

interface CardFrameProps {
  card: Card
  printing?: Printing
  full?: boolean
}

interface CardModalProps {
  card: Card
  printings: Printing[]
  onClose: () => void
}

const RING = "soulmasters"

// Hues taken from the rulebook rarity icons, lightened to stay legible on the dark background.
// Celestial's icon is black with a white starburst, so it reads as white here.
const RARITY_COLORS: Record<string, string> = {
  Common: "#caa872",
  Uncommon: "#a9d161",
  Rare: "#6aaad7",
  Epic: "#aa72da",
  Legendary: "#d85f5a",
  Celestial: "#e8ecf2",
}

const SORTS = ["Set number", "Name", "Faction", "Type", "Cost"] as const
type Sort = (typeof SORTS)[number]

const rarityColor = (rarity: string) => RARITY_COLORS[rarity] ?? "#a8a29e"
const imageUrl = (printing: Printing) => `/${RING}/asset/printing/${printing.image}`
const cleanText = (text: string) => text.replace(/\r/g, "")

// Compact stats shown at the foot of the tile's text box; the modal shows the full list.
// Shield power sits on the left, the combat stats on the right.
const tileStats = (card: Card): { left: [string, string][]; right: [string, string][] } => {
  const left: [string, string][] = []
  const right: [string, string][] = []
  if (card["shield-power"] != null) left.push(["SP", String(card["shield-power"])])
  if (card.attack != null) right.push(["ATK", String(card.attack)])
  if (card["shield-capacity"] != null) right.push(["SHD", String(card["shield-capacity"])])
  if (card.health != null) right.push(["HP", String(card.health)])
  else if (card.hp) right.push(["HP", card.hp])
  return { left, right }
}

const detailRows = (card: Card): [string, string][] => {
  const rows: [string, string | null | number][] = [
    ["Cost", card.cost],
    ["Attack", card.attack],
    ["Shield Capacity", card["shield-capacity"]],
    ["Health", card.health],
    ["Shield Power", card["shield-power"]],
    ["HP", card.hp],
    ["Resource Count", card["resource-count"]],
    ["Core Energy", card["core-energy"]],
    ["Mercenary Limit", card["mercenary-limit"]],
    ["Conversion Rate", card["conversion-rate"]],
    ["Specialization", card.specialization],
  ]
  return rows
    .filter(([, value]) => value != null && value !== "")
    .map(([label, value]) => [label, String(value)])
}

const FilterSelect: React.FC<FilterSelectProps> = ({ label, value, options, allLabel, onChange }) => (
  <label className="flex items-center gap-2">
    {label}
    <select
      className="bg-input border border-border rounded-md px-2 py-1 text-foreground outline-none cursor-pointer focus-visible:border-gray-400"
      value={value}
      onChange={e => onChange(e.target.value)}
    >
      {allLabel != null && <option value="">{allLabel}</option>}
      {options.map(option => <option key={option} value={option}>{option}</option>)}
    </select>
  </label>
)

// Text-rendered proxy frame for cards without a scanned image.
const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <span className="flex gap-1">
    <span className="font-semibold">{label}</span>
    <span className="text-gray-400">{value}</span>
  </span>
)

const CardFrame: React.FC<CardFrameProps> = ({ card, printing, full }) => {
  const { left, right } = tileStats(card)
  return (
    <div className="h-full w-full flex flex-col rounded-lg border border-border bg-navy-800 overflow-hidden text-left">
      <div className="px-3 pt-2.5 pb-1.5">
        <div className="flex items-start justify-between gap-1.5">
          <div className="text-lg font-semibold leading-tight">{card.id}</div>
          {card.cost != null &&
            <div
              className="shrink-0 w-7 h-7 rounded-full border border-border flex items-center justify-center"
              title="Cost"
            >
              {card.cost}
            </div>}
        </div>
        <div className="text-sm uppercase tracking-wider truncate text-gray-400">
          {card.attributes || card.type}
          {card["faction-subtypes"] && ` · ${card["faction-subtypes"]}`}
        </div>
      </div>
      <div className="grow min-h-0 px-3 py-2 flex flex-col gap-2 overflow-hidden">
        <div className={`grow leading-snug text-gray-200 whitespace-pre-line overflow-hidden ${full ? "" : "line-clamp-6"}`}>
          {cleanText(card.text)}
        </div>
        {left.length + right.length > 0 &&
          <div className="shrink-0 flex items-center justify-between gap-2.5 text-sm">
            <div className="flex gap-2.5">
              {left.map(([label, value]) => <Stat key={label} label={label} value={value} />)}
            </div>
            <div className="flex gap-2.5">
              {right.map(([label, value]) => <Stat key={label} label={label} value={value} />)}
            </div>
          </div>}
      </div>
      <div className="px-3 py-2 border-t border-border flex items-center justify-between gap-2 text-sm">
        {printing ? <span className="truncate">{printing.id}</span> : <span />}
        <span className="truncate" style={{ color: rarityColor(card.rarity) }}>{card.rarity}</span>
      </div>
    </div>
  )
}

const CardModal: React.FC<CardModalProps> = ({ card, printings, onClose }) => {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && onClose()
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [onClose])

  const imaged = printings.find(p => p.image)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={card.id}
        className="w-full max-w-4xl max-h-full overflow-auto rounded-xl border border-border bg-pane p-5 flex flex-col sm:flex-row gap-5"
        onClick={e => e.stopPropagation()}
      >
        <div className="w-full sm:w-96 shrink-0 self-center sm:self-start">
          {imaged
            ? <img className="w-full rounded-lg" src={imageUrl(imaged)} alt={card.id} />
            : <div className="aspect-[63/88]"><CardFrame card={card} full /></div>}
        </div>
        <div className="grow min-w-0">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-2xl leading-tight">
              {card.id}
            </h2>
            <button
              className="cursor-pointer text-xl leading-none"
              onClick={onClose}
              aria-label="Close"
            >
              ✕
            </button>
          </div>
          <div className="mt-1 uppercase tracking-wider">
            {card.faction}
            {card["faction-subtypes"] && ` · ${card["faction-subtypes"]}`}
            {" — "}
            {card.attributes || card.type}
          </div>
          <div className="mt-1" style={{ color: rarityColor(card.rarity) }}>
            {card.rarity}
          </div>
          <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
            {detailRows(card).map(([label, value]) => (
              <React.Fragment key={label}>
                <dt>{label}</dt>
                <dd className="text-gray-500">{value}</dd>
              </React.Fragment>
            ))}
          </dl>
          {card.text && (
            <div className="mt-4 leading-relaxed text-gray-200 whitespace-pre-line border-t border-border pt-4">
              {cleanText(card.text)}
            </div>)}
          {printings.length > 0 && (
            <div className="mt-4 border-t border-border pt-4">
              {printings.map(p => (<div key={p.id}>{p.id} — {p.set}</div>))}
            </div>)}
        </div>
      </div>
    </div>
  )
}

const CardBrowser: React.FC = () => {
  const [cards, setCards] = useState<Card[]>([])
  const [printings, setPrintings] = useState<Printing[]>([])
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading")
  const [query, setQuery] = useState("")
  const [faction, setFaction] = useState("")
  const [type, setType] = useState("")
  const [rarity, setRarity] = useState("")
  const [set, setSet] = useState("")
  const [sort, setSort] = useState<Sort>("Set number")
  const [selected, setSelected] = useState<Card | null>(null)

  useEffect(() => {
    setStatus("loading")
    Promise.all([
      fetch(`/api/data/${RING}/card`).then(res => res.json()),
      fetch(`/api/data/${RING}/printing`).then(res => res.json()),
    ])
      .then(([cardRows, printingRows]) => {
        setCards(cardRows)
        setPrintings(printingRows)
        setStatus("ready")
      })
      .catch(() => setStatus("error"))
  }, [])

  const printingsByCard = useMemo(() => {
    const map = new Map<string, Printing[]>()
    for (const printing of printings) {
      const list = map.get(printing.name) ?? []
      list.push(printing)
      map.set(printing.name, list)
    }
    for (const list of map.values()) {
      list.sort((a, b) => a.id.localeCompare(b.id))
    }
    return map
  }, [printings])

  const displayPrinting = (card: Card): Printing | undefined => {
    const list = printingsByCard.get(card.id)
    return list && (list.find(p => p.image) ?? list[0])
  }

  const factions = useMemo(() => [...new Set(cards.map(c => c.faction))].sort(), [cards])
  const types = useMemo(() => [...new Set(cards.map(c => c.type))].sort(), [cards])
  const rarities = useMemo(() => [...new Set(cards.map(c => c.rarity))].sort(), [cards])
  const sets = useMemo(() => [...new Set(printings.map(p => p.set))].sort(), [printings])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const matches = (card: Card) => {
      if (faction && card.faction !== faction) return false
      if (type && card.type !== type) return false
      if (rarity && card.rarity !== rarity) return false
      const cardPrintings = printingsByCard.get(card.id) ?? []
      if (set && !cardPrintings.some(p => p.set === set)) return false
      if (!q) return true
      const haystack = [
        card.id, card.text, card.attributes, card["faction-subtypes"], card.specialization,
        ...cardPrintings.map(p => p.id),
      ].join("\n").toLowerCase()
      return haystack.includes(q)
    }

    const byName = (a: Card, b: Card) => a.id.localeCompare(b.id)
    const setNumber = (card: Card) => printingsByCard.get(card.id)?.[0]?.id ?? "￿"
    const compare: Record<Sort, (a: Card, b: Card) => number> = {
      Name: byName,
      Faction: (a, b) => a.faction.localeCompare(b.faction) || byName(a, b),
      Type: (a, b) => a.type.localeCompare(b.type) || byName(a, b),
      Cost: (a, b) => (a.cost ?? Infinity) - (b.cost ?? Infinity) || byName(a, b),
      "Set number": (a, b) => setNumber(a).localeCompare(setNumber(b)),
    }
    return cards.filter(matches).sort(compare[sort])
  }, [cards, printingsByCard, query, faction, type, rarity, set, sort])

  const clearFilters = () => {
    setQuery("")
    setFaction("")
    setType("")
    setRarity("")
    setSet("")
  }

  return (
    <div className="grow flex flex-col min-h-0">
      <div className="sticky top-0 z-10 shrink-0 flex flex-wrap items-center gap-x-3 gap-y-2 p-3 border-b border-border bg-gray-800">
        <div className="relative w-60">
          <FiSearch
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500"
            aria-hidden="true"
          />
          <input
            className="w-full bg-input border border-border rounded-md pl-9 pr-2.5 py-1 text-foreground outline-none placeholder:text-gray-500 focus-visible:border-gray-400"
            type="search"
            placeholder="Search cards"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>
        <FilterSelect label="Faction" value={faction} options={factions} allLabel="All" onChange={setFaction} />
        <FilterSelect label="Type" value={type} options={types} allLabel="All" onChange={setType} />
        <FilterSelect label="Rarity" value={rarity} options={rarities} allLabel="All" onChange={setRarity} />
        <FilterSelect label="Set" value={set} options={sets} allLabel="All" onChange={setSet} />
        <FilterSelect label="Sort by" value={sort} options={[...SORTS]} onChange={value => setSort(value as Sort)} />
        {status === "ready" &&
          <div className="ml-auto">
            {filtered.length === cards.length ? `${cards.length} cards` : `${filtered.length} of ${cards.length} cards`}
          </div>}
      </div>

      <div className="grow overflow-auto p-3">
        {status === "loading" &&  <div className="h-full flex items-center justify-center">Loading cards…</div>}
        {status === "error" &&
          <div className="h-full flex items-center justify-center">
            Couldn’t load the card database. Check that the server is running, then reload.
          </div>}
        {status === "ready" && filtered.length === 0 &&
          <div className="h-full flex flex-col items-center justify-center gap-2">
            <div>No cards match these filters.</div>
            <button
              className="px-3 py-1 border border-border rounded-md bg-gray-700 text-foreground cursor-pointer hover:bg-hover"
              onClick={clearFilters}
            >
              Clear filters
            </button>
          </div>}
        {status === "ready" && filtered.length > 0 && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-4">
            {filtered.map(card => {
              const printing = displayPrinting(card)
              return (
                <div
                  key={card.id}
                  role="button"
                  tabIndex={0}
                  aria-label={card.id}
                  className="aspect-[63/88] rounded-lg outline-none cursor-pointer ring-orange-400 hover:ring-2 focus-visible:ring-2 motion-safe:transition-shadow"
                  onClick={() => setSelected(card)}
                  onKeyDown={e => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault()
                      setSelected(card)
                    }
                  }}
                >
                  {printing?.image
                    ? <img className="w-full h-full object-cover rounded-lg" src={imageUrl(printing)} alt={card.id} loading="lazy" />
                    : <CardFrame card={card} printing={printing} />}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {selected &&
        <CardModal
          card={selected}
          printings={printingsByCard.get(selected.id) ?? []}
          onClose={() => setSelected(null)}
        />}
    </div>
  )
}

export default CardBrowser
