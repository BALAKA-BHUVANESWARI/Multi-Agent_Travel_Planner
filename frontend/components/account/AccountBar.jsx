export default function AccountBar({ user, authRequired, onOpen, onSignOut }) {
  return (
    <div className="row" id="account">
      {user ? (
        <>
          <span className="muted">{user.email}</span>
          <button id="tripsBtn" onClick={() => onOpen("trips")}>My trips</button>
          <button id="prefsBtn" onClick={() => onOpen("preferences")}>My preferences</button>
          <button id="outBtn" onClick={onSignOut}>Sign out</button>
        </>
      ) : (
        <>
          <span className="muted">{authRequired ? "Sign in to plan" : "Guest"}</span>
          <button id="signBtn" onClick={() => onOpen("signin")}>Sign in / register</button>
        </>
      )}
    </div>
  );
}
