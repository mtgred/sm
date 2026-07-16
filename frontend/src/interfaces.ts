export interface User {
  username: string
  hash: string
}

export interface Session {
  token: string
  user: User
}

export interface GameSettings {
  casual: boolean
}

// A seat in a lobby game; deck fields stay null until the player picks one
export interface LobbyPlayer extends User {
  deck_id: string | null
  deck_name: string | null
  commander_id: string | null
  deck_valid: boolean | null
}

export interface Game {
  id: string
  players: LobbyPlayer[]
  settings: GameSettings
  created_at: string
  started_at?: string
}

export interface EmitData {
  method: string
  ringId: string
  path: string
  data: object
}

export interface EmitFn {
  (event: string, data: string | EmitData, callback?: (response: object) => void): void
}

export type Card = {
  id: string
  type: string
  cost: number | null
  attack: number | null
  health: number | null
  rarity: string
  faction: string
  specialization: string
  attributes: string
  text: string
  hp: string
  "shield-capacity": number | null
  "shield-power": number | null
  "resource-count": string
  "core-energy": string
  "mercenary-limit": string
  "conversion-rate": string
  "faction-subtypes": string
}

export type Printing = {
  id: string
  name: string
  set: string
  image?: string
}

// A physical card in the game state: `id` names the card in the pool, `uid`
// identifies this copy. Energy field cards also carry their orientation:
// face down (any card) or face up (Artifact Cores only), ready or resting.
export interface BoardCard {
  id: string
  uid: string
  faceUp?: boolean
  resting?: boolean
}

export interface CommanderState {
  stages: string[] // card ids in evolution order (Base first)
  stage: number // index into stages
}

export interface PlayerState {
  user: User
  commander: CommanderState
  hp: number
  maxHp: number
  resource: string // the faction's resource name, e.g. "Rage"
  resourceDeck: number
  resourceField: number
  deck: BoardCard[]
  hand: BoardCard[]
  discard: BoardCard[]
  battleground: BoardCard[]
  equipment: BoardCard[]
  battlefield: BoardCard | null
  energyField: BoardCard[]
  energyPlays: number // energy placed this turn (the server enforces the cap)
  reserve: BoardCard[]
  mulliganed: boolean
  prompts: unknown[]
}

export interface ChatMessage {
  user?: User
  msg: string
}

export interface GameState {
  round: number
  phase: string
  firstPlayer: number
  activePlayer: number | null
  winner?: number // player index, set when phase becomes "over"
  log: ChatMessage[]
  players: PlayerState[]
}
