import React from "react"
import type { Session, EmitFn, GameState } from "./interfaces"

interface GameBoardProps {
  id?: string
  session?: Session
  emit: EmitFn
  gamestate: GameState
}

const GameBoard: React.FC<GameBoardProps> = ({ id, session, emit, gamestate }) => {
  return (
    <div className="grow flex flex-wrap overflow-auto content-start p-3 gap-3">
      Game Board
    </div>
  )
}

export default GameBoard
