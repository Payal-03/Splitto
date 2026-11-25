import { useState, useEffect } from "react";
import { getTrips } from "./api";
import "./index.css";

export default function App() {
  const [trips, setTrips] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getTrips().then(setTrips).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="app">
      <header>
        <h1>💸 Splitto</h1>
        <p className="tagline">Split smart. Settle easy.</p>
      </header>

      <main>
        <h2>Your Trips</h2>
        {error && <p className="error">{error}</p>}
        {!trips && !error && <p>Loading trips…</p>}
        {trips && (
          <ul className="trip-list">
            {trips.map((trip) => (
              <li key={trip.id} className="trip-card">
                <strong>{trip.name}</strong>
                <span>
                  {trip.members.length} members · {trip.expenses.length} expenses
                </span>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
