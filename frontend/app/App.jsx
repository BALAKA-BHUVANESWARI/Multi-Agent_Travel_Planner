// The page: header, optional panels, the request form and the planner's answer.
import { useState } from "react";
import PreferencesPanel from "../components/account/PreferencesPanel.jsx";
import SignInPanel from "../components/account/SignInPanel.jsx";
import TripsPanel from "../components/account/TripsPanel.jsx";
import ErrorBoundary from "../components/common/ErrorBoundary.jsx";
import EmergencyPanel from "../components/emergency/EmergencyPanel.jsx";
import Footer from "../components/layout/Footer.jsx";
import Header from "../components/layout/Header.jsx";
import PlanMessage from "../components/plan/PlanMessage.jsx";
import PlanResult from "../components/plan/PlanResult.jsx";
import GroupEditor from "../components/planner/GroupEditor.jsx";
import PromptCard from "../components/planner/PromptCard.jsx";
import { useAccount } from "../hooks/useAccount.js";
import { useGroup } from "../hooks/useGroup.js";
import { usePlanner } from "../hooks/usePlanner.js";
import { api } from "../services/api.js";
import { NO_PLAN_STATUSES } from "../services/constants.js";
import { placeName } from "../services/format.js";

export default function App() {
  const account = useAccount();
  const group = useGroup();
  const planner = usePlanner(group.read);
  const [prompt, setPrompt] = useState("");
  const [panel, setPanel] = useState({ name: "", id: 0 });
  const [emergencyOpen, setEmergencyOpen] = useState(false);

  const openPanel = (name) => setPanel((p) => ({ name, id: p.id + 1 }));
  const closePanel = () => openPanel("");
  const signIn = () => {
    openPanel("signin");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const signOut = async () => {
    await account.signOut();
    closePanel();
    planner.clear();
  };

  const result = planner.result;
  const tripName = result && !NO_PLAN_STATUSES.includes(result.status)
    ? placeName(result.constraints, "destination") : "";

  return (
    <main>
      <Header user={account.user} authRequired={account.authRequired} onOpen={openPanel} onSignOut={signOut}
        onToggleEmergency={() => setEmergencyOpen((open) => !open)} />

      <div id="sos">
        {emergencyOpen && (
          <EmergencyPanel tripName={tripName} thread={result?.thread_id} onClose={() => setEmergencyOpen(false)} />
        )}
      </div>
      <div id="panel">
        {panel.name === "signin" && (
          <SignInPanel key={panel.id} onClose={closePanel}
            onSignedIn={(token, user) => { account.signIn(token, user); closePanel(); }} />
        )}
        {panel.name === "trips" && (
          <TripsPanel key={panel.id} onClose={closePanel}
            onOpenTrip={(trip) => { planner.show(trip); closePanel(); }} />
        )}
        {panel.name === "preferences" && (
          <PreferencesPanel key={panel.id} onClose={closePanel}
            onDeleted={() => { account.forget(); closePanel(); }} />
        )}
      </div>

      <PromptCard text={prompt} onText={setPrompt} onPlan={planner.plan} busy={planner.busy}>
        <GroupEditor rows={group.rows} onChange={group.change} onAdd={group.add} onRemove={group.remove} />
      </PromptCard>

      <PlanMessage result={result} error={planner.error} />
      <fieldset className="plain" id="plan" disabled={planner.busy}>
        {result && (
          <ErrorBoundary key={planner.version}>
            <PlanResult result={result} lastRequest={planner.lastRequest.current}
              onPlan={planner.plan} onResult={planner.show} onRun={planner.run} onSignIn={signIn}
              onDecide={(decision) => planner.run(() => api(`/approve/${result.thread_id}`, decision))} />
          </ErrorBoundary>
        )}
      </fieldset>

      <Footer health={account.health} />
    </main>
  );
}
