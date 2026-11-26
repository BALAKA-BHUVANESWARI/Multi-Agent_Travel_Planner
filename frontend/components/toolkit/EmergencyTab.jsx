import { useState } from "react";
import Banner from "../common/Banner.jsx";
import EmergencyLookup from "../emergency/EmergencyLookup.jsx";
import EmergencyResult from "../emergency/EmergencyResult.jsx";

export default function EmergencyTab({ data, thread }) {
  const [searching, setSearching] = useState(false);
  return (
    <>
      <Banner kind="bad">{data.call_first}</Banner>
      <div id="tripHelp">
        {searching ? <EmergencyLookup request={{ thread_id: thread, nearby: true }} /> : (
          <>
            <EmergencyResult result={data} />
            <button type="button" className="findNear" onClick={() => setSearching(true)}>
              Find hospitals and pharmacies nearby
            </button>
          </>
        )}
      </div>
    </>
  );
}
