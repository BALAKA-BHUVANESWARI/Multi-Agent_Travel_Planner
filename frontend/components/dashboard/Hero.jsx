import AccountBar from "../account/AccountBar.jsx";
import Icon from "./Icon.jsx";
import Logo from "./Logo.jsx";
import Photo from "./Photo.jsx";

const PILLS = ["Smart suggestions", "Any city or town", "You approve before booking"];

export default function Hero({ onToggleEmergency, ...account }) {
  return (
    <section className="hero">
      <Photo titles={["Taj Mahal"]} art="monument" alt="The Taj Mahal in Agra" width={1280} className="hero-photo"
        fit="xMaxYMax meet" />
      <div className="hero-top">
        <button type="button" className="sos" id="sosBtn" onClick={onToggleEmergency}>🆘 Emergency help</button>
        <AccountBar {...account} />
      </div>
      <div className="hero-text">
        <h1>
          <span className="hero-name"><span className="logo"><Logo size={36} /></span>ExecuTrip:</span>{" "}
          <span className="hero-tagline"><b>Wish-to-Way</b><i aria-hidden="true">{"✈︎"}</i></span>
        </h1>
        <p>Plan, explore and get personalised travel plans, built by a team of AI agents.</p>
        <ul>
          {PILLS.map((pill) => <li key={pill}><span><Icon name="check" size={13} /></span>{pill}</li>)}
        </ul>
      </div>
    </section>
  );
}
