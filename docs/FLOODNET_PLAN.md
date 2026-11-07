# FloodNet: AI-assisted distributed rescue simulation

**Implementation plan | 4 people | 5 hours**

> Neptune North Challenge ("Actors work better together"). The n8n with Claude sponsor track is an optional add-on.

## 1. Objective

Build a simulation of independent rescue teams, each assisted by AI, that work from limited local
information, keep working during communication failures, and exchange information through a
courier drone.

**Core demo:** A rescue team finds a civilian group and loses contact with another area. It keeps
working on its own, and **its AI brain goes offline with the radio**, so it falls back to simple
rules. A drone physically carries new information across the gap. The isolated team updates what
it knows and responds. Turning the drone off in a second run shows the difference it makes.

## 2. How we meet the judging criteria

| Criterion | How we show it |
|---|---|
| Working towards a common goal | A shared score: civilians rescued, out of the total |
| Independent decision-making | Each team (and the drone) decides from **its own map of what it knows**. The AI only recommends, and Python checks every recommendation |
| Resilience when comms fail | Teams keep rescuing while disconnected. The AI is cut off too, so teams fall back to rules. The drone carries messages across the gap |
| Something we're excited about | Teams explain their AI choices in the live feed, the drone visibly carries information, and a comparison of drone on vs drone off |

## 3. MVP features

- **Simulation:** 20×20 grid, a fixed flood progression, **3–4 rescue teams, 6–8 civilian groups**
  and one shelter. The numbers are config values, so start at 2 teams and 3 groups and scale up once it works.
- **Independent agents:** each team senses its surroundings, keeps its own map of what it knows,
  and picks a target (the AI recommends one, Python checks it, and rules take over if needed).
- **Communication:** two radio areas, with a control to break and restore the link between them.
- **AI access depends on the radio:** a team can only reach the AI model while its area is
  connected. Disconnected teams use the rule fallback automatically.
- **Courier drone:** stores messages and forwards them later. It makes one decision of its own:
  fly to the area whose information is **oldest**. It can fall back to a fixed route.
- **Deliberate conflict:** one civilian group sits **on the border**, reachable from both areas,
  so both sides claim it while disconnected. Claims made while disconnected are provisional. On
  reconnection, the conflicting future tasks are resolved, and a pickup that has already happened
  can't be repeated.
- **Dashboard:** live map, team positions, civilian status, comms status, each team's own map,
  and an event feed that includes the AI's reasons.
- **Proof:** the same scenario and seed run with **drone ON vs drone OFF**, with the scores side
  by side (for example, 8/8 rescued vs 5/8).

## 4. How AI is used

Physical simulation and every important change to the world stay deterministic Python. AI is used for:

1. **Rescue decisions:** a team sends only what it knows to the AI model and asks for a
   recommended target, a short explanation, and what information is missing.
2. **Situation summaries:** the AI turns simulation state into a short operational briefing,
   highlighting information that is stale or incomplete.
3. **Drone intelligence (optional):** the AI summarises the observations the drone is carrying,
   without changing their original timestamps or which observer reported them.

**AI rules:**

- **Called only when something happens:** a new civilian appears in the team's map, its claim is
  lost, it reconnects, or its current task finishes. It is never called on every simulation step.
- **3-second time limit, without blocking.** The team keeps its current target while waiting. A
  late reply is ignored if the situation has changed since.
- **Checked in Python:** the target must exist in the team's own map and must not be already
  rescued or claimed by someone else. If not, use the fallback: the nearest known available target.
- **No AI while disconnected:** a team in a disconnected area falls back to rules straight away.
- **Demo safety:** cache replies keyed by (seed, prompt), and keep a global **"AI off"** switch.
- Model: Claude Haiku-class, with structured JSON output. Keep `ANTHROPIC_API_KEY` in `.env` only.

**Optional sponsor integration:** n8n with two Claude roles, one assessing the situation and one
drafting the briefing. Keep this outside the movement loop. **Test one n8n → Claude call
early (by about 1:00)** so any setup problems show up in good time.

## 5. Five-hour schedule and ownership

| Time | Person A: Simulation | Person B: AI and agents | Person C: Network | Person D: Dashboard |
|---|---|---|---|---|
| 0:00–0:20 | Agree shared data structures and demo | Agree agent and AI inputs/outputs | Agree message format | Agree dashboard layout |
| 0:20–1:15 | Grid, flood, movement, pickup | Local sensing, belief maps, basic decisions | Message delivery and snapshots. **Test n8n → Claude once** | Dashboard with sample data, `st.fragment` refresh |
| 1:15–2:15 | Shelter drop-off and scoring | Claims and AI recommendations (event-triggered, with time limit) | Radio integration, AI access tied to connectivity | Live map, score and event feed |
| 2:15–3:15 | Scenario tuning: border civilian group, scale to 3–4 teams and 6–8 groups | Disconnection and conflict handling | Drone relay, message storage, "fly to oldest area" choice | Team map views and link-failure control |
| 3:15–4:00 | Integration and testing, drone ON/OFF comparison run | AI situation summaries, reply cache, AI-off switch | Optional n8n/Claude integration | Explain stale and pending information in the UI, comparison panel |
| 4:00–5:00 | Bug fixes | Bug fixes | Bug fixes | Record demo and prepare presentation |

## 6. Technical approach

- **Language:** Python
- **Simulation and agents:** simple Python classes
- **Data validation:** Pydantic
- **Dashboard:** Streamlit. Keep the simulation in `st.session_state` or `st.cache_resource` and
  refresh only the map panel with `@st.fragment(run_every="1s")`. Provide play, pause and
  single-step controls.
- **Visualisation:** Plotly
- **AI:** Claude (Haiku-class) with structured JSON replies
- **Optional workflow:** n8n with Claude

Use a deterministic step-by-step scheduler rather than letting each agent run on its own clock:

1. Deliver any messages that can be delivered (according to links and drone position).
2. Give each agent its local observations.
3. Let each agent update what it knows and choose an action (using AI replies that have already
   arrived, otherwise the current target or the fallback).
4. Check actions and apply them to the world.
5. Update the dashboard.

Keep the original observation timestamp and observer ID when messages are forwarded, so old
information can't overwrite newer observations.

## 7. Priorities and scope control

**Must deliver:** independent team decisions, a separate map of what each team knows,
communication failure, drone store-and-forward, reconnection, a border conflict that actually
happens, and a working dashboard.

**Should deliver:** AI access tied to connectivity, event-triggered AI with time limit and
fallback, and the drone ON/OFF comparison.

**Only if time allows:** AI summaries, the n8n/Claude workflow, and more advanced task allocation.

**Do not build:** complex auctions, trucks, tower mechanics, freehand blackout painting, flood
forecasting, Redis, or full replay functionality.

## 8. Demo script (3 minutes)

1. **(0:00)** Problem: in floods, comms fail first, and teams have to act on what they know.
2. **(0:20)** Start the seeded scenario. Teams find civilians, and the feed shows their AI
   reasoning ("Team-2: group at (12,4) is closest, water rising, no claim seen").
3. **(0:50)** **Break the link.** Area B's teams switch to "isolated, rules only" and keep
   rescuing. Their map views go out of date.
4. **(1:30)** The drone picks the area with the oldest information and flies over. The event
   "drone delivered 6 observations" appears. Team-3's map updates and it changes target.
5. **(2:00)** **Reconnect.** The border group was claimed by both sides. The conflict is resolved
   in the feed, and no pickup is repeated.
6. **(2:30)** Show the comparison panel: same seed, drone ON vs drone OFF.
7. **(2:50)** Wrap up: decisions use local information, the AI recommends but never overrides,
   and comms failure slows the response without stopping it.

## 9. Failure tests

| Test | Expected outcome |
|---|---|
| The same message is delivered twice (directly and via the drone) | Applied once |
| An old observation arrives after a newer one | Ignored (the original timestamp wins) |
| Both areas claim the border group while disconnected | Resolved on reconnect. Only one pickup |
| The AI is slow (more than 3 s) or returns bad JSON | The team keeps its target or uses the fallback. No crash |
| The AI recommends a target that is rescued or unknown | Rejected in Python and the fallback is used |
| A team is in a disconnected area | No AI calls are attempted. It runs on rules only |
| Run with AI switched off | The demo still works from start to finish |

## 10. Success criteria

The demo should clearly show that:

- Teams make decisions using their own local information.
- Teams keep working when communication is interrupted, including without AI.
- The drone physically carries information between disconnected areas, and chooses where to go.
- New information changes a team's map and its next decisions.
- Reconnection exposes and resolves conflicting task claims.
- AI recommendations can be explained and can't override simulation rules.
- The drone ON vs OFF comparison shows a measurable difference.

**Build the drone-relay rescue scenario first.** Everything else comes second to making that demonstration reliable.
