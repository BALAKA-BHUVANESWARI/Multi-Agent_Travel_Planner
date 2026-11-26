import { Fragment } from "react";
import { phoneHref, phoneNumbers, safeUrl } from "../../services/format.js";

export function ExternalLink({ link }) {
  if (!link) return null;
  return <a href={safeUrl(link.url)} target="_blank" rel="noopener noreferrer">{link.title}</a>;
}

export function LinkList({ links }) {
  return (links || []).map((link, i) => (
    <Fragment key={i}>{i > 0 && " · "}<ExternalLink link={link} /></Fragment>
  ));
}

// "100 or 112" becomes two numbers you can tap to call
export function PhoneLinks({ value }) {
  return phoneNumbers(value).map((number, i) => (
    <Fragment key={i}>
      {i > 0 && <> <span className="muted">or</span> </>}
      <a href={phoneHref(number)}>{number}</a>
    </Fragment>
  ));
}
