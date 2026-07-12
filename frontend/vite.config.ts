import react from '@vitejs/plugin-react'
import { resolve } from "path"
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
  ],
  build: {
    outDir: "../../fireball/frontend/dist/soulmasters/js",
    assetsDir: "",
    rollupOptions: {
      external: ["react", "react-dom", "react/jsx-runtime"],
      output: {
        entryFileNames: "[name].js",
        globals: {
          react: "React",
          "react-dom": "ReactDOM",
          "react/jsx-runtime": "jsxRuntime",
        },
      },
    },
    lib: {
      entry: {
        cardbrowser: resolve(__dirname, "src/CardBrowser.tsx"),
        deckbuilder: resolve(__dirname, "src/DeckBuilder.tsx"),
        lobby: resolve(__dirname, "src/Lobby.tsx"),
        gameboard: resolve(__dirname, "src/GameBoard.tsx"),
      },
      formats: ["es"],
    },
  },
})
