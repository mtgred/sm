import React, { useEffect, useState } from "react"
import UserView from "./UserView"
import type { EmitFn, Game, LobbyPlayer, Session } from "./interfaces"

// Game lobby, modeled on the Dune Uprising one: the games list lives in
// fireball's store (seeded via /api/query, updated by `lobby` socket
// broadcasts), and every action is an emit that the platform forwards to
// server/main.py's POST /games. The player's decks (for the picker inside a
// joined game) come through the same authenticated /api/query tunnel — the
// browser never talks to the soulmasters server directly.

const RING_ID = "soulmasters"
const GAME_SIZE = 2
const STAGE_SUFFIX = /\s*\((Base|Evol\. 1|Evol\. 2)\)$/
const commanderName = (id: string | null) => id?.replace(STAGE_SUFFIX, "") ?? null

// Subset of the deckbuilder's SavedDeck that the picker needs
interface DeckSummary {
  id: string
  name: string
  commander_id: string
  casual: boolean
  is_valid: boolean
}

const formatLabel = (casual: boolean) => (casual ? "Casual" : "Competitive")

const PlayerRow: React.FC<{ player: LobbyPlayer }> = ({ player }) => (
  <div className="flex items-center gap-3 mb-3">
    <UserView user={player} />
    {player.deck_name ?
      <>
        <span className="text-gray-300 truncate">
          {player.deck_name}
          {commanderName(player.commander_id) && ` — ${commanderName(player.commander_id)}`}
        </span>
        {player.deck_valid === false &&
          <span className="bg-red-900 text-red-100 px-2 rounded whitespace-nowrap">Not legal</span>}
      </>
     : <span className="text-gray-400 italic">Choosing a deck…</span>}
  </div>
)

interface LobbyProps {
  games: Game[]
  session?: Session
  emit: EmitFn
}

const Lobby: React.FC<LobbyProps> = ({ games, session, emit }) => {
  const [creating, setCreating] = useState(false)
  const [casual, setCasual] = useState(false)
  const [decks, setDecks] = useState<DeckSummary[]>([])
  const [decksStatus, setDecksStatus] = useState<"loading" | "error" | "ready">("loading")

  const send = (data: object) => emit("lobby", { method: "post", ringId: RING_ID, path: "games", data })

  // On a rejected action (e.g. two players race for the last seat) fireball
  // broadcasts the error body instead of a game list; keep the last good list.
  const gameList = Array.isArray(games) ? games : []
  const username = session?.user?.username
  const joinedGame = username
    ? gameList.find(game => game.players.some(player => player.username === username)) ?? null
    : null
  const me = joinedGame?.players.find(player => player.username === username)

  useEffect(() => {
    if (joinedGame?.id) {
      emit("joinChannel", `${RING_ID}/game/${joinedGame.id}`)
    }
  }, [joinedGame?.id, emit])

  // The player's saved decks, for the picker inside a joined game
  useEffect(() => {
    if (!session?.token) {
      setDecksStatus("ready")
      return
    }
    setDecksStatus("loading")
    fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.token}` },
      body: JSON.stringify({ method: "get", ringId: RING_ID, path: "decks" }),
    })
      .then(res => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((list: DeckSummary[]) => {
        setDecks(list)
        setDecksStatus("ready")
      })
      .catch(() => setDecksStatus("error"))
  }, [session?.token])

  // Illegal decks are offered too (flagged both here and in the player list) —
  // only the format has to match, which is what the server enforces.
  const formatDecks = joinedGame ? decks.filter(deck => deck.casual === joinedGame.settings.casual) : []

  const canStart =
    joinedGame != null &&
    joinedGame.players.length === GAME_SIZE &&
    joinedGame.players.every(player => player.deck_id)

  return (
    <div className="p-4 flex flex-col h-full">
      <div className="mx-auto grow pane rounded-lg overflow-hidden w-[1096px]">
        <div className="grow flex h-full">
          <div className="flex flex-col border-r border-gray-600 w-1/2">
            <div className="p-4">
              <button
                onClick={() => setCreating(true)}
                disabled={!session || !!joinedGame || creating}
              >
                New Game
              </button>
            </div>

            <div className="grow overflow-auto px-4 py-0.5">
              {gameList.length === 0 &&
                <div className="text-gray-400 p-3">No games yet — create one.</div>}
              {gameList.map(game => (
                <div
                  key={game.id}
                  className={`p-3 mb-2 border border-gray-600 rounded-md flex justify-between items-center ${joinedGame?.id === game.id ? "selected" : ""}`}
                >
                  <div>
                    <div className="flex gap-2 mb-3">
                      <span className="bg-gray-700 px-2 rounded">{formatLabel(game.settings.casual)}</span>
                      {game.started_at && <span className="bg-gray-700 px-2 rounded">In progress</span>}
                    </div>
                    <div className="flex items-center gap-4">
                      {game.players.map(player => (
                        <UserView key={player.username} user={player} />
                      ))}
                      {Array.from({ length: GAME_SIZE - game.players.length }).map((_, i) => (
                        <div key={`empty-${i}`} className="w-6 h-6 border border-gray-600 rounded" />
                      ))}
                    </div>
                  </div>

                  {session && !joinedGame && !game.started_at && game.players.length < GAME_SIZE &&
                    <button onClick={() => send({ action: "join", id: game.id })}>
                      Join
                    </button>}
                </div>
              ))}
            </div>
          </div>

          {creating && !joinedGame &&
            <div className="p-4">
              <h2 className="text-2xl font-bold mb-6">New Game</h2>
              <label className="flex items-center cursor-pointer gap-2">
                <input
                  type="checkbox"
                  className="cursor-pointer accent-sky-500"
                  checked={casual}
                  onChange={e => setCasual(e.target.checked)}
                />
                <span className="font-medium">Casual (5-card reserve decks)</span>
              </label>
              <div className="flex gap-3 mt-6">
                <button
                  onClick={() => {
                    setCreating(false)
                    send({ action: "create", settings: { casual } })
                  }}
                >
                  Create
                </button>
                <button onClick={() => setCreating(false)}>Cancel</button>
              </div>
            </div>}

          {joinedGame && joinedGame.started_at &&
            // The live path is fireball's `start` broadcast, which navigates
            // everyone in the game channel; this covers coming back to the
            // lobby (e.g. a reload) while the game is still running.
            <div className="p-4 grow min-w-0">
              <h2 className="text-2xl mb-4 font-bold">
                {formatLabel(joinedGame.settings.casual)} game in progress
              </h2>
              <div className="flex items-center gap-3">
                <button onClick={() => window.location.assign(`/${RING_ID}/game/${joinedGame.id}`)}>
                  Return to game
                </button>
                <button onClick={() => send({ action: "leave", id: joinedGame.id })}>
                  Leave
                </button>
              </div>
              <div className="text-gray-400 mt-3">Leaving a game in progress quits it for good.</div>
            </div>}

          {joinedGame && !joinedGame.started_at && (
            <div className="p-4 grow min-w-0">
              <div className="flex items-center gap-3 mb-4">
                <button
                  disabled={!canStart}
                  title={canStart ? undefined : "Waiting for a full game with every deck chosen"}
                  onClick={() => send({ action: "start", id: joinedGame.id })}
                >
                  Start
                </button>
                <button onClick={() => send({ action: "leave", id: joinedGame.id })}>
                  Leave
                </button>
              </div>

              <h2 className="text-2xl mb-4 font-bold">{formatLabel(joinedGame.settings.casual)} game</h2>

              <h3 className="mb-2 text-lg font-semibold">Players</h3>
              {joinedGame.players.map(player => <PlayerRow key={player.username} player={player} />)}
              {joinedGame.players.length < GAME_SIZE &&
                <div className="text-gray-400 italic mb-3">Waiting for an opponent…</div>}

              <h3 className="mt-6 mb-2 text-lg font-semibold">Your deck</h3>
              {decksStatus === "loading" && <div>Loading your decks…</div>}
              {decksStatus === "error" &&
                <div className="text-red-400">
                  Couldn't load your decks. Check that the deckbuilder server is running, then reload.
                </div>}
              {decksStatus === "ready" && formatDecks.length === 0 &&
                <div className="text-gray-400">
                  No {formatLabel(joinedGame.settings.casual).toLowerCase()} decks —
                  build one in the deck builder first.
                </div>}
              {decksStatus === "ready" && formatDecks.length > 0 && (
                <>
                  <select
                    className="w-full max-w-96 cursor-pointer"
                    aria-label="Your deck"
                    value={me?.deck_id ?? ""}
                    onChange={e => send({ action: "deck", id: joinedGame.id, deck_id: e.target.value })}
                  >
                    {!me?.deck_id && <option value="">Choose a deck</option>}
                    {formatDecks.map(deck => (
                      <option key={deck.id} value={deck.id}>
                        {deck.name} — {commanderName(deck.commander_id)}
                        {!deck.is_valid && " (illegal)"}
                      </option>
                    ))}
                  </select>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Lobby
