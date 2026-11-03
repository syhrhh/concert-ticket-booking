import React from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

function App() {
  return (
    <main>
      <h1>Concert Ticket Booking</h1>
      <p>Distributed Systems Proof of Concept</p>
      <p>Frontend starter is ready. Connect this UI to the FastAPI services.</p>
    </main>
  )
}

createRoot(document.getElementById('root')).render(<App />)
