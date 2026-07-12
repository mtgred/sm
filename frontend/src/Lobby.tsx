import React from "react"
import type { EmitFn, Game, Session } from "./interfaces"

interface LobbyProps {
  games: Game[]
  session?: Session
  emit: EmitFn
}

const Lobby: React.FC<LobbyProps> = ({ games, session, emit }) => {
  const send = (data: object) => {
    emit("lobby", { method: "post", ringId: "uprising", path: "games", data })
  }

  return (
    <div className="grow flex flex-wrap overflow-auto content-start p-3 gap-3">
      Game Board
    </div>
  )
}

export default Lobby

