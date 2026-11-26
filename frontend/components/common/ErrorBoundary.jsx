// If one part of the page cannot be drawn, show a message there and keep the rest (above all emergency help) working.
// Give it a new `key` to try again with new data.
import { Component } from "react";
import Banner from "./Banner.jsx";

export default class ErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <Banner kind="bad">This part of the page could not be shown. Plan the trip again or reload the page.</Banner>;
  }
}
