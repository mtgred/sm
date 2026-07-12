export interface User {
  username: string
  hash: string
}

export interface Session {
  token: string
  user: User
}

export interface Game {
  id: string
  name: string
  players: User[]
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
