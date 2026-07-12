import React from "react"
import type { Card } from "./interfaces"

interface CardBrowserProps {
  cards: Card[]
}

const CardBrowser: React.FC<CardBrowserProps> = () => {
  return (
    <div className="grow flex flex-wrap overflow-auto content-start p-3 gap-3">
      Card Browser
    </div>
  )
}

export default CardBrowser
