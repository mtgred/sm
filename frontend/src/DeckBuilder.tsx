import React from "react"

interface DeckBuilderProps {
}

const DeckBuilder: React.FC<DeckBuilderProps> = () => {
  return (
    <div className="grow flex flex-wrap overflow-auto content-start p-3 gap-3">
      Deck Builder
    </div>
  )
}

export default DeckBuilder
