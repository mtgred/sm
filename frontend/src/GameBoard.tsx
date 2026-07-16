import React, { useEffect, useState } from "react"
import UserView from "./UserView"
import type { BoardCard, Card, ChatMessage, EmitFn, GameState, PlayerState, Printing, Session } from "./interfaces"

// Renders the game state built by server/game_setup.py. Like the lobby,
// nothing here talks to the soulmasters server directly: actions are `game`
// socket emits that fireball forwards to POST /game/{id} and broadcasts the
// updated state back to everyone in the soulmasters/game/{id} channel.
// Currently covers setup (zones, opening hands, the mulligan decision),
// energy plays (face-down energy, face-up Artifact Cores and core swaps),
// resting energy to pay costs (click ready energy, then confirm) and the turn
// cycle: End turn passes to the opponent, whose upkeep readies their cards
// and resets the per-turn energy allowance before they draw.

const RING = "soulmasters"

// The slice of GET /rules the board needs (see server/rules.py). Fetched
// rather than hardcoded so the server stays the single source of truth; if
// the fetch fails the buttons stay enabled and the server still enforces.
interface TurnRules {
  energyPlaysPerTurn: number
  firstTurnEnergyPlays: number
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

const CARD = "w-24 aspect-[5/7] shrink-0"

interface CardViewProps {
  id: string
  pool: CardPool
  selected?: boolean
  onClick?: () => void
}

// A card on the table: scanned image when a printing has one, otherwise a small text proxy.
const CardView: React.FC<CardViewProps> = ({ id, pool, selected, onClick }) => {
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
      className={`${CARD} rounded-md ${selected ? "outline-3 outline-sky-400 -translate-y-2" : ""} ${onClick ? "cursor-pointer" : ""}`}
      title={id}
      onClick={onClick}
    >
      {frame}
    </div>
  )
}

// Face-down pile (main deck, opponent hand/reserve) with a count badge.
const Pile: React.FC<{ count: number; tone?: "gold" | "orange" }> = ({ count, tone = "gold" }) => (
  <div
    className={`${CARD} relative rounded-md border ${
      tone === "orange"
        ? "border-orange-950 bg-gradient-to-br from-orange-700 to-orange-950"
        : "border-amber-950 bg-gradient-to-br from-amber-600 to-amber-900"
    } ${count === 0 ? "opacity-25" : ""}`}
  >
    <div className="absolute inset-0 flex items-center justify-center text-xl font-bold text-white/90">
      {count}
    </div>
  </div>
)

// A card in the energy field. The owner sees face-down cards (the rulebook
// lets you look at your own face-down energy any time); everyone else sees a
// card back. Resting cards tilt sideways.
interface EnergyCardProps {
  card: BoardCard
  mine: boolean
  pool: CardPool
  selected?: boolean
  onClick?: () => void
}

const EnergyCard: React.FC<EnergyCardProps> = ({ card, mine, pool, selected, onClick }) => {
  const resting = card.resting ? "rotate-12" : ""
  if (!card.faceUp && !mine) {
    return (
      <div
        className={`${CARD} rounded-md border border-amber-950 bg-gradient-to-br from-amber-600 to-amber-900 ${resting}`}
        title="Face-down energy"
      />
    )
  }
  return (
    <div className={`relative shrink-0 ${resting}`}>
      <CardView id={card.id} pool={pool} selected={selected} onClick={onClick} />
      {!card.faceUp &&
        <div className="absolute inset-x-0 bottom-0 rounded-b-md bg-black/70 text-center text-[10px] uppercase tracking-wider text-gray-300 pointer-events-none">
          Face down
        </div>}
    </div>
  )
}

const Zone: React.FC<{ label: string; grow?: boolean; children?: React.ReactNode }> = ({ label, grow, children }) => (
  <div className={`flex flex-col gap-1 min-w-0 ${grow ? "grow" : ""}`}>
    <div className="text-xs uppercase tracking-wider text-gray-400">{label}</div>
    <div className="flex gap-2 min-h-32 rounded-md border border-dashed border-gray-600 p-1.5 overflow-x-auto">
      {children}
    </div>
  </div>
)

interface PanelProps {
  player: PlayerState
  active: boolean
  flipped: boolean // opponent panel: hand row on top, zones below
  pool: CardPool
  mine?: boolean // the viewer owns this panel and may see face-down energy
  selectedEnergy?: string[] // energy cards staged to swap back to hand or to rest
  onEnergyClick?: (uid: string) => void
  children?: React.ReactNode // hand + reserve row (owner-dependent, passed in)
}

const PlayerPanel: React.FC<PanelProps> = ({ player, active, flipped, pool, mine, selectedEnergy, onEnergyClick, children }) => {
  const commanderId = player.commander.stages[player.commander.stage]
  return (
    <div className={`pane rounded-lg p-3 flex gap-3 ${flipped ? "flex-col-reverse" : "flex-col"}`}>
      <div className="flex items-center gap-4">
        <UserView user={player.user} />
        <span className="bg-red-900 text-red-100 px-2 rounded whitespace-nowrap">
          ♥ {player.hp}/{player.maxHp}
        </span>
        <span className="bg-gray-700 px-2 rounded whitespace-nowrap">
          {player.resource} {player.resourceField}/{player.resourceField + player.resourceDeck}
        </span>
        {active && <span className="bg-sky-900 text-sky-100 px-2 rounded">Active turn</span>}
      </div>

      <div className="flex gap-3">
        <Zone label="Commander">
          {commanderId && <CardView id={commanderId} pool={pool} />}
        </Zone>
        <Zone label="Equipment">
          {player.equipment.map(card => <CardView key={card.uid} id={card.id} pool={pool} />)}
        </Zone>
        <Zone label="Battlefield">
          {player.battlefield && <CardView id={player.battlefield.id} pool={pool} />}
        </Zone>
        <Zone label="Battleground" grow>
          {player.battleground.map(card => <CardView key={card.uid} id={card.id} pool={pool} />)}
        </Zone>
        <Zone label="Deck">
          <Pile count={player.deck.length} />
        </Zone>
        <Zone label="Discard">
          {player.discard.length > 0 &&
            <CardView id={player.discard[player.discard.length - 1].id} pool={pool} />}
        </Zone>
      </div>

      <div className="flex gap-3">
        <Zone label={`Energy field (${player.energyField.length})`} grow>
          {player.energyField.map(card =>
            <EnergyCard
              key={card.uid}
              card={card}
              mine={!!mine}
              pool={pool}
              selected={selectedEnergy?.includes(card.uid)}
              onClick={onEnergyClick ? () => onEnergyClick(card.uid) : undefined}
            />)}
        </Zone>
        {children}
      </div>
    </div>
  )
}

const LogView: React.FC<{ log: ChatMessage[] }> = ({ log }) => (
  <div className="pane rounded-lg p-2 w-72 shrink-0 flex flex-col min-h-0">
    <div className="grow overflow-auto space-y-1">
      {log.map((entry, i) => (
        <div key={i} className="leading-snug">
          {entry.user && <span className="font-semibold">{entry.user.username} </span>}
          <span className="text-gray-300">{entry.msg}</span>
        </div>
      ))}
    </div>
  </div>
)

interface GameBoardProps {
  id?: string
  session?: Session
  emit: EmitFn
  gamestate: GameState
}

const GameBoard: React.FC<GameBoardProps> = ({ id, session, emit, gamestate }) => {
  const pool = useCardPool()
  const rules = useTurnRules()
  const [returning, setReturning] = useState<string[]>([])
  // Energy play staging: a hand card picked to place, and (for a face-up
  // Artifact Core) an energy card picked to swap back to hand.
  const [playing, setPlaying] = useState<string | null>(null)
  const [swap, setSwap] = useState<string | null>(null)
  // Ready energy cards staged to rest (paying a cost), confirmed as one action.
  const [restUids, setRestUids] = useState<string[]>([])
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
  // Only Artifact Cores may be played face up, which is also when a swap is allowed
  const playingCore = !!playingCard && pool.cards.get(playingCard.id)?.type === "Core"
  const stageEnergy = (uid: string) => {
    setSwap(null)
    setRestUids([])
    setPlaying(current => (current === uid ? null : uid))
  }
  const playEnergy = (faceUp: boolean) => {
    send({ action: "energy", data: { uid: playing, faceUp, swap: faceUp ? swap : null } })
    setPlaying(null)
    setSwap(null)
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
  const endTurn = () => {
    setPlaying(null)
    setSwap(null)
    setRestUids([])
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
    <div className="grow flex overflow-hidden p-3 gap-3">
      <div className="grow flex flex-col gap-3 min-w-0 overflow-auto">
        <PlayerPanel player={opponent} active={gamestate.activePlayer === top} flipped pool={pool}>
          <Zone label={`Hand (${opponent.hand.length})`}>
            {opponent.hand.length > 0 && <Pile count={opponent.hand.length} />}
          </Zone>
          <Zone label={`Reserve (${opponent.reserve.length})`}>
            {opponent.reserve.length > 0 && <Pile count={opponent.reserve.length} tone="orange" />}
          </Zone>
        </PlayerPanel>

        <div className="flex items-center gap-3 px-1">
          <span className="grow">{status}</span>
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
              <button disabled={returning.length === 0} onClick={() => confirmMulligan(returning)}>
                Return {returning.length} card{returning.length === 1 ? "" : "s"}
              </button>
              <button onClick={() => confirmMulligan([])}>Keep hand</button>
            </>}
          {playingCard &&
            <>
              {playingCore &&
                <span className="text-gray-400 whitespace-nowrap">
                  {swap ? "Swapping 1 energy card back to hand" : "Click your energy to swap a card back"}
                </span>}
              <button onClick={() => playEnergy(false)}>Play face down as energy</button>
              {playingCore &&
                <button onClick={() => playEnergy(true)}>Play face up{swap ? " and swap" : ""}</button>}
              <button onClick={() => stageEnergy(playingCard.uid)}>Cancel</button>
            </>}
          {restUids.length > 0 && !playingCard &&
            <>
              <span className="text-gray-400 whitespace-nowrap">Resting energy pays that much 💠</span>
              <button onClick={restEnergy}>
                Rest {restUids.length} energy
              </button>
              <button onClick={() => setRestUids([])}>Cancel</button>
            </>}
          {myTurn && me && !playingCard &&
            <>
              {energyAllowance !== null &&
                <span className="text-gray-400 whitespace-nowrap">
                  Energy plays {me.energyPlays}/{energyAllowance}
                </span>}
              <button onClick={endTurn}>End turn</button>
            </>}
        </div>

        <PlayerPanel
          player={gamestate.players[bottom]}
          active={gamestate.activePlayer === bottom}
          flipped={false}
          pool={pool}
          mine={!!me}
          selectedEnergy={playingCore ? (swap ? [swap] : []) : restUids}
          onEnergyClick={
            playingCore
              ? uid => setSwap(current => (current === uid ? null : uid))
              : canRest
                ? toggleRest
                : undefined
          }
        >
          <Zone label={`Hand (${gamestate.players[bottom].hand.length})`}>
            {me ? me.hand.map((card: BoardCard) =>
              <CardView
                key={card.uid}
                id={card.id}
                pool={pool}
                selected={mulliganing ? returning.includes(card.uid) : card.uid === playing}
                onClick={mulliganing ? () => toggle(card.uid) : canPlayEnergy ? () => stageEnergy(card.uid) : undefined}
              />)
              : gamestate.players[bottom].hand.length > 0 && <Pile count={gamestate.players[bottom].hand.length} />}
          </Zone>
          <Zone label={`Reserve (${gamestate.players[bottom].reserve.length})`}>
            {me ? me.reserve.map(card => <CardView key={card.uid} id={card.id} pool={pool} />)
              : gamestate.players[bottom].reserve.length > 0 && <Pile count={gamestate.players[bottom].reserve.length} tone="orange" />}
          </Zone>
        </PlayerPanel>
      </div>

      <LogView log={gamestate.log} />
    </div>
  )
}

export default GameBoard
