// The dashboard: side menu, trip form, agent status, the planner's answer and places to explore.
import { useState } from "react";
import PreferencesPanel from "../components/account/PreferencesPanel.jsx";
import SignInPanel from "../components/account/SignInPanel.jsx";
import TripsPanel from "../components/account/TripsPanel.jsx";
import ErrorBoundary from "../components/common/ErrorBoundary.jsx";
import AgentPipeline, { pipelineState } from "../components/dashboard/AgentPipeline.jsx";
import DashboardCards from "../components/dashboard/DashboardCards.jsx";
import Hero from "../components/dashboard/Hero.jsx";
import PlanForm from "../components/dashboard/PlanForm.jsx";
import Sidebar from "../components/dashboard/Sidebar.jsx";
import TopDestinations from "../components/dashboard/TopDestinations.jsx";
import EmergencyPanel from "../components/emergency/EmergencyPanel.jsx";
import Footer from "../components/layout/Footer.jsx";
import PlanMessage from "../components/plan/PlanMessage.jsx";
import PlanResult from "../components/plan/PlanResult.jsx";
import GroupEditor from "../components/planner/GroupEditor.jsx";
import { useAccount } from "../hooks/useAccount.js";
import { useGroup } from "../hooks/useGroup.js";
import { usePlanner } from "../hooks/usePlanner.js";
import { api } from "../services/api.js";
import { NO_PLAN_STATUSES } from "../services/constants.js";
import { placeName } from "../services/format.js";

const NEW_TRIP = { from: "", to: "", date: "", days: "4", travellers: "2", budget: "", interests: [] };

// scrolls after the screen has been updated
const scrollTo = (id) => setTimeout(() => {
  if (id) document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  else window.scrollTo({ top: 0, behavior: "smooth" });
}, 0);

export default function App() {
  const account = useAccount();
  const group = useGroup();
  const planner = usePlanner(group.read);
  const [prompt, setPrompt] = useState("");
  const [tab, setTab] = useState("form");
  const [trip, setTrip] = useState(NEW_TRIP);
  const [nav, setNav] = useState("home");
  const [panel, setPanel] = useState({ name: "", id: 0 });
  const [emergencyOpen, setEmergencyOpen] = useState(false);

  const openPanel = (name) => {
    setPanel((p) => ({ name, id: p.id + 1 }));
    if (name) scrollTo("panel");
  };
  const closePanel = () => openPanel("");
  const signIn = () => openPanel("signin");
  const signOut = async () => {
    await account.signOut();
    closePanel();
    planner.clear();
  };

  const startPlan = (text, members) => {
    planner.plan(text, members);
    scrollTo("pipeline");
  };
  const showForm = () => {
    setTab("form");
    scrollTo("planForm");
  };

  const select = (key) => {
    setNav(key);
    if (key === "home") scrollTo("");
    else if (key === "explore") scrollTo("top10");
    else if (key === "insights") scrollTo("insights");
    else if (key === "trips") openPanel(account.user ? "trips" : "signin");
    else if (key === "profile") openPanel(account.user ? "preferences" : "signin");
    else {
      setEmergencyOpen(true);
      scrollTo("sos");
    }
  };

  const result = planner.result;
  const tripName = result && !NO_PLAN_STATUSES.includes(result.status)
    ? placeName(result.constraints, "destination") : "";

  return (
    <div className="shell">
      <Sidebar active={nav} onSelect={select} />
      <main>
        <Hero user={account.user} authRequired={account.authRequired} onOpen={openPanel} onSignOut={signOut}
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
              onOpenTrip={(saved) => { planner.show(saved); closePanel(); scrollTo("pipeline"); }} />
          )}
          {panel.name === "preferences" && (
            <PreferencesPanel key={panel.id} onClose={closePanel}
              onDeleted={() => { account.forget(); closePanel(); }} />
          )}
        </div>

        <PlanForm tab={tab} onTab={setTab} form={trip} onForm={setTrip} text={prompt} onText={setPrompt}
          onPlan={startPlan} onExplore={() => select("explore")} busy={planner.busy}>
          <GroupEditor rows={group.rows} onChange={group.change} onAdd={group.add} onRemove={group.remove} />
        </PlanForm>

        <AgentPipeline state={pipelineState(planner)} />

        <PlanMessage result={result} error={planner.error} />
        <fieldset className="plain" id="plan" disabled={planner.busy}>
          {result && (
            <ErrorBoundary key={planner.version}>
              <PlanResult result={result} lastRequest={planner.lastRequest.current}
                onPlan={startPlan} onResult={planner.show} onRun={planner.run} onSignIn={signIn}
                onDecide={(decision) => planner.run(() => api(`/approve/${result.thread_id}`, decision))} />
            </ErrorBoundary>
          )}
        </fieldset>

        <TopDestinations chosen={trip.to}
          onPick={(place) => { setTrip((t) => ({ ...t, to: place.name, days: String(place.days) })); showForm(); }} />

        <ErrorBoundary key={"tiles" + planner.version}>
          <DashboardCards result={result} date={trip.date} interests={trip.interests}
            onView={() => scrollTo("msg")} onStart={showForm} />
        </ErrorBoundary>

        <Footer health={account.health} />
      </main>
    </div>
  );
}
