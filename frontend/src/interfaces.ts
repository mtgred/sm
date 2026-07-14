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

export interface ChooseOption {
  label: string
  cost?: Record<string, number>
}

export interface Prompt {
  type: string
  choices?: string[] | ChooseOption[]
  count?: number
  amount?: number
  effects?: Record<string, unknown>
  options?: string[]
  min?: number
  max?: number
  spaces?: string[]
  factions?: string[]
  faction?: string
  deepCover?: boolean
  posts?: string[]
  space?: string
  maxCommanders?: number
  maxTotal?: number
  factionBonus?: Record<string, unknown>
  passive?: boolean
  contracts?: string[]
}

export interface Player {
  user: User
  hand: Card[]
  deck: Card[]
  discard: Card[]
  commander: Card
}

export interface ChatMessage {
  user?: User
  msg: string
}

export interface GameState {
  log: ChatMessage[]
  players: Player[]
}
