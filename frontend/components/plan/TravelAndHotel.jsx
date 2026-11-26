// The chosen way of travelling and the chosen hotel, side by side.
import { inr, shortDay } from "../../services/format.js";
import { PriceBadge, PriceSource } from "../common/PriceBadge.jsx";

const unavailable = <span className="muted">Unavailable (tool failure)</span>;

export default function TravelAndHotel({ transport, hotel, travelWord }) {
  const option = transport?.selected;
  const room = hotel?.selected;
  const journey = option && transport.journey;
  return (
    <div className="grid2">
      <div className="card">
        <b>{travelWord}</b> <PriceBadge block={transport} /><br />
        {!option ? unavailable : (
          <>
            {option.label}<br />
            Out {option.depart_out} → {option.arrive_out} · back {option.depart_back}
            {journey?.extra_days > 0 && (
              <><br />Leave home <b>{shortDay(journey.leave_date)}</b> · back home <b>{shortDay(journey.home_date)}</b></>
            )}
            <br /><b>{inr(option.price_pp)}</b> per person round trip
            <PriceSource block={transport} />
            {transport.footprint && (
              <div className="muted" style={{ fontSize: 13 }}>
                🌱 about {String(transport.footprint.kg_pp)} kg CO₂e per person, there and back (estimate)
              </div>
            )}
          </>
        )}
      </div>
      <div className="card">
        <b>Hotel</b> <PriceBadge block={hotel} /><br />
        {!room ? unavailable : (
          <>
            {room.label}<br />
            {inr(room.price_night_per_room)}/room/night × {room.nights} nights × {room.rooms} room(s)<br />
            <b>{inr(room.total)}</b>
            <PriceSource block={hotel} />
          </>
        )}
      </div>
    </div>
  );
}
