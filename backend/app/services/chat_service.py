"""The chatbot: one message in, one reply out. It uses the same planner as the form.

It can start a plan, supply a detail the planner asked for, request changes to a plan that is waiting for approval,
and answer questions about the plan on screen. It can never approve, book or cancel: those stay buttons, so a
misheard or mistyped word cannot book anything.

The server keeps no chat history. The page says which plan is on screen (its thread id), and everything else comes
from that saved plan. What the message means is decided by rules; an AI model is only asked to word an answer when
no rule can, and it sees nothing but the plan.
"""
from __future__ import annotations

import json
import re

from app.core.utils import fmt_inr
from app.data import gazetteer
from app.observability import recorder as observe
from app.services import ai_guard, fact_checks
from app.services import request_parser as parser
from app.services.feedback_parser import parse_feedback

# ------------------------------------------------------------------ what a message is
_GREETING = re.compile(r"^(hi+|hello|hey|namaste|good (morning|afternoon|evening))\b[\s!.]*$", re.I)
_HELP = re.compile(r"^(help|what can (you|i) (do|ask)\??|how (does this|do you) work\??)[\s!.]*$", re.I)
_THANKS = re.compile(r"^(thanks?|thank you|thx)\b.{0,20}$", re.I)
_RESET = re.compile(r"^(start over|start again|never ?mind|forget (it|that)|reset)[\s!.]*$", re.I)
# entry rules get a fixed answer: this app never says whether a visa is needed
_VISA = re.compile(r"\bvisas?\b|\bimmigration\b|\bentry (requirements?|rules?|permit)\b|"
                   r"\bneed (a |my |our )?passports?\b", re.I)
_EMERGENCY = re.compile(r"\b(emergency|ambulance|police|hospital|doctor|fire brigade|sos|helpline)\b", re.I)
_NOT_AN_EMERGENCY = re.compile(r"\bmuseum\b", re.I)
_QUESTION = re.compile(r"^(what|whats|what's|when|where|which|who|why|how|is|are|am|do|does|did|will|would|can|could|"
                       r"should|may|tell me|show|list|give me)\b", re.I)
# worded like a question, but asking for a change: "can you make it cheaper?"
_CHANGE_FORM = re.compile(
    r"^(?:(?:ok(?:ay)?|and|also|so)[,\s]+)?(?:please\s+)?(?:(?:can|could|will|would)\s+(?:you|we)\s+(?:please\s+)?)?"
    r"(?:make|change|add|remove|skip|drop|move|switch|shift|increase|reduce|lower|set|use|go by|travel by|upgrade|"
    r"extend|shorten|give me (?:a )?(?:more|less|cheaper)|i want|we want|more|less|no\b|budget\s*(?:to|is|:)?\s*\d|"
    r"cheaper|relaxed|slower)\b", re.I)
_BOOKING = re.compile(r"^(?:(?:yes|ok(?:ay)?|sure)[,!\s]*)?(?:please\s+)?(?:(?:can|could|will|would)\s+you\s+)?"
                      r"(?:approve|book|confirm|cancel|pay)\b|\b(?:approve|book|confirm|cancel|pay for)\s+"
                      r"(?:it|this|that|my|the)\b", re.I)
_YES = re.compile(r"^(yes|yeah|yep|ok(ay)?|sure|go ahead|do it|proceed)[\s!.]*$", re.I)
_NEW_TRIP = re.compile(r"\b(plan|organi[sz]e|arrange|suggest|create|book me)\b.*"
                       r"\b(trip|holiday|vacation|getaway|tour|itinerary|honeymoon)\b", re.I)
_CHANGE_PLACE = re.compile(r"\binstead\b|\b(change|switch)\s+(the\s+)?(destination|place|city)\b", re.I)
_TRAVEL_HINT = re.compile(r"\b(trip|holiday|vacation|getaway|honeymoon|go to|going to|visit|travel to)\b", re.I)


def is_question(text: str) -> bool:
    return bool(_QUESTION.match(text)) or text.rstrip().endswith("?")


def is_new_plan(text: str, constraints: dict | None, strategy: str = "normal") -> bool:
    """Is this a request for a whole new trip, and not a change or a question about the one on screen?"""
    asks_for_trip = bool(_NEW_TRIP.search(text))
    _, destination, _ = parser.parse_places(text)
    days = parser.parse_days(text)
    if constraints is not None:
        if _CHANGE_PLACE.search(text):
            return False
        if asks_for_trip:
            return bool(destination or days) or not parse_feedback(text, constraints, strategy)["recognized"]
        return bool(destination and days) and not _CHANGE_FORM.match(text) and not is_question(text)
    if asks_for_trip:
        return True
    return not is_question(text) and bool(destination or _TRAVEL_HINT.search(text))


def is_separate_request(text: str) -> bool:
    """While the planner is waiting for a detail, a short reply adds to the request. Only a full new request ("plan
    a trip ...", or a place with a number of days) replaces it."""
    if _NEW_TRIP.search(text):
        return True
    _, destination, _ = parser.parse_places(text)
    return bool(destination and parser.parse_days(text))


# ------------------------------------------------------------------ answering the planner's question
_MARKERS = re.compile(r"\s*\|.*$", re.S)
_AMOUNT = re.compile(r"^₹?\s*\d[\d,]*(\.\d+)?\s*(k|l|lakhs?|rs|inr|rupees)?$", re.I)
_PLACE = re.compile(r"^[^\W\d_][^\d|]{1,59}$")
_LEAD = re.compile(r"^(?:(?:let'?s|i want to|we want to)\s+)?(?:go(?:ing)?\s+to\s+|visit\s+|take (?:me|us) to\s+)",
                   re.I)


def _with_marker(request: str, marker: str, value: str) -> str:
    request = re.sub(rf"\s*\|\s*{marker}:[^|]*", "", request, flags=re.I)
    return f"{request} | {marker}: {value}"


def _place_answer(check: dict, answer: str) -> str | None:
    """The place chosen in reply to "Did you mean ...?": the suggestion, the name as typed, or another name."""
    said = re.sub(r"^(?:yes|no)\b[\s,]*|^(?:i (?:mean|meant)|it'?s|it is)\s+", "", answer.strip(), flags=re.I)
    said = _LEAD.sub("", said).replace("=", " ").strip(" .!,?")
    if not said:
        return check["suggested"] if re.match(r"yes\b", answer.strip(), re.I) else None
    low = f"{gazetteer.normalize(said)} "
    for name in (check["suggested"], check["typed"]):           # "Goa", "Goa, India"
        if low.startswith(f"{gazetteer.normalize(name)} "):
            return name
    if re.fullmatch(r"yeah|yep|correct|right|sure|ok(?:ay)?", said, re.I):
        return check["suggested"]
    return said if _PLACE.match(said) and len(said.split()) <= 4 else None


def complete_request(state: dict, text: str) -> str:
    """The earlier request plus what the traveller has just added to it."""
    request = state.get("request") or ""
    answer = " ".join(text.replace("|", " ").split()).strip(" .!")
    check = state.get("place_check")
    if check:                                                  # the answer to "Did you mean ...?"
        chosen = _place_answer(check, answer)
        if chosen:
            typed = check["typed"].replace("=", " ").replace("|", " ")
            return f"{request} | place: {typed} = {chosen}"
    options = state.get("travel_options")
    if options:
        low = answer.lower()
        mode = parser.parse_travel_mode("by " + low) or parser.parse_travel_mode(low)
        if mode is None and re.search(r"\b(any|cheapest|best)\b", low):
            mode = "auto"
        if mode:
            return _with_marker(request, "travel", "any mode" if mode == "auto" else f"by {mode}")
    constraints = state.get("constraints") or {}
    missing = [k for k in ("origin", "destination", "days", "budget") if not constraints.get(k)]
    if state.get("suggestions") or missing == ["destination"]:
        place = _LEAD.sub("", answer)
        if _PLACE.match(place):
            return _with_marker(request, "destination", place)
    pieces, places = [], [k for k in ("origin", "destination") if k in missing]
    chosen_destination = None
    # a comma inside a number ("60,000") does not separate two answers
    parts = [p.strip() for p in re.split(r",(?!\d{2,3}\b)|;|\band\b", answer) if p.strip()]

    def bare_place(piece: str) -> bool:
        return bool(_PLACE.match(piece)) and len(piece.split()) <= 4 \
            and not re.match(r"(from|to|in|on|by|budget|for)\b", piece, re.I)
    # one place on its own, when both ends are missing, is where they want to go; two come in the order asked
    if len(places) == 2 and sum(map(bare_place, parts)) == 1 and not re.search(r"\bfrom\b", answer, re.I):
        places = ["destination"]
    for piece in parts:
        number = re.sub(r"[₹,\s]|rs|inr|rupees", "", piece.lower())
        if "days" in missing and number.isdigit() and int(number) <= 30:
            pieces.append(f"{number} days")
        elif "budget" in missing and _AMOUNT.match(piece):
            pieces.append(f"budget {piece.replace(',', '').lstrip('₹ ')}")
        elif places and bare_place(piece):
            if places.pop(0) == "origin":
                pieces.append(f"from {piece}")
            else:
                chosen_destination = piece
        else:
            if re.match(r"from\b", piece, re.I) and "origin" in places:
                places.remove("origin")
            pieces.append(piece)
    base = _MARKERS.sub("", request)
    markers = request[len(base):]
    out = ", ".join([base.rstrip(" .,!"), *pieces]) + markers
    return _with_marker(out, "destination", chosen_destination) if chosen_destination else out


# ------------------------------------------------------------------ answers from the saved plan
def _name(constraints: dict, role: str) -> str:
    return (constraints.get(f"{role}_geo") or {}).get("name") or str(constraints.get(role) or "").title()


def _day_text(day: dict) -> str:
    lines = [f"Day {day['day']} ({day['date']}):"]
    lines += [f"• {i['start']} {i['name']}" for i in day.get("items", [])]
    w = day.get("weather")
    if w:
        lines.append(f"Weather: {w.get('tmax')}°/{w.get('tmin')}°C, {w.get('precip_prob')}% chance of rain.")
    return "\n".join(lines)


def _transport_text(state: dict) -> str | None:
    picked = (state.get("flight") or {}).get("selected")
    if not picked:
        return None
    mode = str(picked.get("mode") or "flight").title()
    kind = "estimated" if picked.get("estimated", True) else "live price when planned"
    return (f"{mode}: {picked.get('label', '')}. Out {picked.get('depart_out', '?')} → "
            f"{picked.get('arrive_out', '?')}, back {picked.get('depart_back', '?')} → "
            f"{picked.get('arrive_back', '?')}. {fmt_inr(picked.get('total', 0))} in total ({kind}).")


def _hotel_text(state: dict) -> str | None:
    picked = (state.get("hotel") or {}).get("selected")
    if not picked:
        return None
    kind = "estimated" if picked.get("estimated", True) else "live price when planned"
    return (f"Hotel: {picked.get('label', '')}. {fmt_inr(picked.get('price_night_per_room', 0))} a night per room, "
            f"{picked.get('nights')} nights, {picked.get('rooms')} room(s): {fmt_inr(picked.get('total', 0))} ({kind}).")


def _budget_text(state: dict) -> str | None:
    report = state.get("budget_report")
    if not report:
        return None
    lines = ", ".join(f"{k} {fmt_inr(v)}" for k, v in report.get("lines", {}).items())
    left = report.get("remaining", 0)
    verdict = f"{fmt_inr(left)} left over" if left >= 0 else f"{fmt_inr(-left)} over budget"
    return (f"Estimated total {fmt_inr(report.get('total', 0))} of your {fmt_inr(report.get('budget', 0))} budget "
            f"({verdict}). That is {lines}. About {fmt_inr(report.get('per_person', 0))} per person.")


def _weather_text(state: dict) -> str | None:
    weather = state.get("weather") or {}
    days = weather.get("days") or []
    if not days:
        return None
    lines = [f"{d['date']}: {d.get('tmax')}°/{d.get('tmin')}°C, {d.get('precip_prob')}% rain" for d in days]
    return "\n".join([*lines, f"Source: {weather.get('source', 'not stated')}."])


def _food_text(state: dict) -> str | None:
    dining = (state.get("activities") or {}).get("dining") or {}
    lines = []
    for key, title in (("veg", "Vegetarian"), ("nonveg", "Non-vegetarian"), ("other", "More places")):
        names = [r["name"] for r in dining.get(key) or []][:3]
        if names:
            lines.append(f"{title}: {', '.join(names)}")
    return "\n".join([*lines, "Details are in “Where to eat” on the page."]) if lines else None


def _overview(state: dict) -> str | None:
    days = (state.get("itinerary") or {}).get("days") or []
    if not days:
        return None
    lines = []
    for day in days:
        names = [i["name"] for i in day.get("items", []) if i.get("type") == "activity"]
        lines.append(f"Day {day['day']}: {', '.join(names) or 'travel'}")
    return "\n".join(lines)


_TOPICS = (
    (r"\b(hotel|stay|room|accommodation)\b", _hotel_text),
    (r"\b(flights?|fly|train|bus|transport|travel time|departure|arrival|depart|arrive)\b|how (do|will) (i|we) "
     r"(get|reach|travel)", _transport_text),
    (r"\b(weather|rain|rainy|temperature|hot|cold|umbrella|climate)\b", _weather_text),
    (r"\b(eat|food|restaurants?|veg|vegetarian|lunch|dinner)\b", _food_text),
    (r"\b(cost|price|budget|total|spend|expensive|money|how much)\b", _budget_text),
    (r"\b(itinerary|overview|summary|summarise|summarize|whole plan|the plan|my plan|all days)\b", _overview),
)


def rule_answer(state: dict, text: str) -> str | None:
    """An answer taken straight from the saved plan, or None when no rule covers the question."""
    low = text.lower()
    days = (state.get("itinerary") or {}).get("days") or []
    number = re.search(r"\bday\s*(\d{1,2})\b", low)
    if days and (number or re.search(r"\b(first|last) day\b", low)):
        wanted = int(number.group(1)) if number else (days[0]["day"] if "first day" in low else days[-1]["day"])
        for day in days:
            if day["day"] == wanted:
                return _day_text(day)
        return f"This plan has days 1 to {days[-1]['day']}."
    if re.search(r"\b(booked|booking|status)\b", low):
        if state.get("status") == "booked":
            return f"It is booked (MOCK booking {state['booking']['booking_id']}). No real booking or payment was made."
        return f"Nothing is booked. {state.get('message', '')}".strip()
    if re.search(r"\bwarnings?\b", low):
        return "\n".join(state.get("warnings") or ["This plan has no warnings."])
    for pattern, build in _TOPICS:
        if re.search(pattern, low):
            # "is the hotel near the beach?" asks something the plan's figures cannot say
            if re.search(r"\b(near|far from|distance|walking|safe|best way|recommend)\b", low):
                return None
            if build is _food_text:
                return build(state) or ("This plan has no restaurant list. A map search for restaurants near your "
                                        "hotel is a quick way to find some.")
            return build(state)
    return None


_AI_SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
_AI_SYSTEM = (
    "You answer a traveller's question about the trip plan given in the data. Use only that data. If it does not "
    "contain the answer, say that the plan does not say. Never invent places, prices, times, phone numbers or "
    "opening hours. Never say whether a visa is needed and never give emergency numbers. You cannot book, cancel or "
    "change anything, so never say that you did. Prices marked estimated are estimates. Answer in at most four short "
    "sentences of plain text.")


def plan_facts(state: dict) -> dict:
    """What the AI model is shown: the plan only. No group members, saved preferences or logs."""
    c = state.get("constraints") or {}
    itinerary = state.get("itinerary") or {}
    activities = state.get("activities") or {}
    return {
        "trip": {"from": _name(c, "origin"), "to": _name(c, "destination"), "days": c.get("days"),
                 "start_date": c.get("start_date"), "travelers": c.get("travelers"), "status": state.get("status")},
        "transport": _transport_text(state), "hotel": _hotel_text(state), "budget": _budget_text(state),
        "weather": _weather_text(state),
        "itinerary": [{"day": d["day"], "items": [{"time": i["start"], "name": i["name"],
                                                    "about": (i.get("desc") or "")[:100]} for i in d["items"]]}
                      for d in itinerary.get("days") or []],
        "restaurants": _food_text(state),
        "top_sights": [s.get("name") for s in activities.get("top_sights") or []],
        "warnings": state.get("warnings") or [],
    }


def ai_answer(state: dict, text: str, llm) -> str | None:
    if llm is None or not llm.available("chat"):
        return None
    user = json.dumps({"question": text, "plan": plan_facts(state)}, ensure_ascii=False, default=str)
    found = llm.complete_json("chat", _AI_SYSTEM, user, _AI_SCHEMA)
    answer = " ".join(str((found or {}).get("answer") or "").split())[:800]
    if not answer:
        return None
    c = state.get("constraints") or {}
    held = ai_guard.unsupported(answer, [plan_facts(state), (state.get("flight") or {}).get("journey")],
                                start_date=c.get("start_date"), days=c.get("days"))
    observe.event("guardrail", "chat_facts", "rejected" if held else "ok", kinds=held)
    fact_checks.record_text("chat", answer, lambda: [plan_facts(state), (state.get("flight") or {}).get("journey")],
                            start_date=c.get("start_date"), days=c.get("days"), shown=not held, question=text)
    return None if held else answer


# ------------------------------------------------------------------ the conversation
def reply(text: str, source: str = "rules", result: dict | None = None, suggestions: list | None = None,
          actions: list | None = None) -> dict:
    return {"reply": text, "source": source, "result": result,
            "suggestions": [{"label": s, "send": s} if isinstance(s, str) else s for s in suggestions or []],
            "actions": actions or []}


HELP = ("I can plan a trip, change it and answer questions about it. For example: “3 days in Goa from Delhi, "
        "budget 30000”. With a plan on screen, try “what's the total cost?”, “show day 2” or “make it cheaper”. "
        "Booking and cancelling are done only with the buttons on the page.")
NO_PLAN_SUGGESTIONS = ["Plan a 4 day trip to Goa from Delhi, budget 60k for 2"]
PLAN_SUGGESTIONS = ["What's the total cost?", "Show day 2", "What's the weather?"]
CHANGE_SUGGESTIONS = ["Make it cheaper", "More food", "Relaxed pace"]


def _plan_suggestions(state: dict) -> list[str]:
    can_change = state.get("status") == "awaiting_approval" \
        and (state.get("pending_approval") or {}).get("can_revise")
    return PLAN_SUGGESTIONS + (CHANGE_SUGGESTIONS[:2] if can_change else [])


def _question_choices(state: dict) -> list[dict]:
    check = state.get("place_check")
    if check:
        return [{"label": check["suggested_label"], "send": check["suggested"]},
                {"label": check["found_label"], "send": check["typed"]}]
    if state.get("travel_options"):
        picks = [{"label": f"{o['label']} · about {fmt_inr(o['price_pp'])} each", "send": o["label"]}
                 for o in state["travel_options"] if o.get("available")]
        return [*picks, {"label": "Any mode", "send": "any mode"}]
    return [{"label": s["name"], "send": s["name"]} for s in (state.get("suggestions") or [])[:5]]


def _asking(state: dict) -> str:
    if state.get("place_check"):
        return f"{str(state.get('message', '')).split(' Reply ')[0]} Pick one below, or type another place."
    if state.get("travel_options"):
        lead = str(state.get("message", "")).split("\n")[0].split(" Reply with")[0]
        return f"{lead} Pick one below, or type it."
    if state.get("suggestions"):
        return "Where would you like to go? Pick a suggestion below, or type any city or town."
    return f"{state.get('message', '')} Type the missing details, or “start over”."


def describe(state: dict) -> dict:
    """The reply for a planner result."""
    if state.get("status") == "blocked":
        return reply(state.get("message", "I can't plan that."))
    if state.get("status") == "needs_info":
        return reply(_asking(state), result=state, suggestions=_question_choices(state))
    c = state.get("constraints") or {}
    report = state.get("budget_report") or {}
    lines = []
    if state.get("notice"):
        lines.append(state["notice"])
    lines.append(f"Your {c.get('days')}-day plan for {_name(c, 'destination')} is on the page: about "
                 f"{fmt_inr(report.get('total', 0))} of your {fmt_inr(report.get('budget', 0))} budget (estimate).")
    if report.get("over_budget"):
        lines.append("It is over your budget. See the warnings on the page.")
    if state.get("status") == "awaiting_approval":
        lines.append("Nothing is booked. To book it, use the “Approve & book” button.")
    return reply(" ".join(lines), result=state, suggestions=_plan_suggestions(state), actions=["show_plan"])


def respond(message: str, state: dict | None, *, plan, revise, ask_ai) -> dict:
    """``state`` is the saved plan on screen, or None. ``plan(text, group)`` and ``revise(feedback)`` run the planner;
    ``ask_ai(state, question)`` may return an answer or None. There is deliberately no way to approve from here."""
    text = " ".join(message.split())
    status = (state or {}).get("status")
    asking = state if status == "needs_info" else None
    shown = state if state and state.get("itinerary") and status != "needs_info" else None

    if _VISA.search(text):
        observe.event("guardrail", "chat_fixed_reply", "blocked", topic="visa")
        return reply("I can't say whether you need a visa. Check with the destination country's embassy or official "
                     "government website.")
    if _EMERGENCY.search(text) and not _NOT_AN_EMERGENCY.search(text):
        observe.private_request()                         # never keep what was said about an emergency
        observe.event("guardrail", "chat_fixed_reply", "blocked", topic="emergency")
        return reply("If anyone is in danger, call the local emergency services now. “Emergency help” on this page "
                     "shows numbers and nearby help.", actions=["open_emergency"])
    if _GREETING.match(text) or _HELP.match(text):
        return reply(HELP if not asking else _asking(asking),
                     suggestions=_question_choices(asking) if asking
                     else _plan_suggestions(shown) if shown else NO_PLAN_SUGGESTIONS)
    if _THANKS.match(text):
        return reply("You're welcome.")
    if _RESET.match(text):
        if asking:
            return reply("Okay, I've dropped that request. Tell me about the trip you want.", actions=["clear"],
                         suggestions=NO_PLAN_SUGGESTIONS)
        return reply("Tell me about the new trip you want.", suggestions=NO_PLAN_SUGGESTIONS)

    constraints = shown.get("constraints") if shown else None
    wants_new = is_separate_request(text) if asking \
        else is_new_plan(text, constraints, (shown or {}).get("strategy", "normal"))
    if wants_new:
        return describe(plan(text, None))

    if _BOOKING.search(text) or (shown and _YES.match(text)):
        if shown:
            observe.event("guardrail", "chat_fixed_reply", "blocked", topic="booking")
            return reply("I can't approve, book or cancel from the chat, so a wrong word can't book anything. Please "
                         "use the buttons on the page.", actions=["show_plan"])
        if not asking:
            observe.event("guardrail", "chat_fixed_reply", "blocked", topic="booking")
            return reply("There's no plan yet. Tell me about your trip first; booking is done with a button after "
                         "you've seen the plan.", suggestions=NO_PLAN_SUGGESTIONS)

    if asking:
        if is_question(text) and not _CHANGE_FORM.match(text):
            return reply(_asking(asking), suggestions=_question_choices(asking))
        return describe(plan(complete_request(asking, text), asking.get("group")))

    if not shown:
        return reply(HELP, suggestions=NO_PLAN_SUGGESTIONS)

    feedback = parse_feedback(text, constraints, shown.get("strategy", "normal"))
    if feedback["recognized"] and (not is_question(text) or _CHANGE_FORM.match(text)):
        if status != "awaiting_approval":
            return reply("This trip can't be changed any more. Ask me to plan a new trip.")
        if not (shown.get("pending_approval") or {}).get("can_revise"):
            return reply("You've used all the changes for this plan. Approve or cancel it with the buttons, or ask me "
                         "to plan a new trip.", actions=["show_plan"])
        return describe(revise(text))

    found = rule_answer(shown, text)
    if found:
        return reply(found, suggestions=_plan_suggestions(shown))
    found = ask_ai(shown, text)
    if found:
        return reply(found, source="ai", suggestions=_plan_suggestions(shown))
    return reply("I can't answer that from this plan. Ask me about the cost, travel, hotel, weather, food or a "
                 "particular day, or ask for a change such as “make it cheaper”.",
                 suggestions=_plan_suggestions(shown))
