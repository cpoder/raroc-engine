# OpenRAROC — corporate + partner demo

**Audience.** Two profiles in the same room.
- **Companies** — CFOs, treasurers, finance directors at mid-cap corporates who borrow.
- **Partners** — advisors who serve those companies: treasury consultancies, debt advisory boutiques, fractional CFO firms, accountancies with corporate finance practices.
Both want the same outcome: *better deals from banks*. The deck is built for both at once; the closing slide splits the ask.

**Length.** 10–15 minutes + Q&A.
**Tone.** Pro-buyer, anti-opacity. The bank is the opposing party in a negotiation — frame it that way without being adversarial. The hero of the talk is **Sabine**, fictional CFO of Nordwind, who signed the wrong deal last quarter and is using OpenRAROC to do better next time.

> **Before the talk: read `GLOSSARY.md` once.** It's the speaker cheat sheet — every acronym in the deck (RAROC, PD, LGD, EAD, K, FPE, GRR, EL, CTI, IRB, output floor, hurdle rate, Pillar 3, CR6, RCF, CCF…) explained in plain English with "if asked, say:" one-liners. You're presenting to a mixed audience: half of them already know these terms, half don't. You need to be fluent enough to define a term in a sentence without losing momentum.

**Files in this folder.**

- `openraroc_demo.pptx` — 12 slides (16:9, dark theme, matches openraroc.com). **Speaker notes are embedded** — open in PowerPoint Presenter View.
- `GLOSSARY.md` — the cheat sheet. Read once before; keep open on a second screen during.
- `build_deck.py` — regenerator. If a number changes, fix it in `demo_numbers.py` first, verify, then re-run this.
- `demo_numbers.py` — engine driver. Reproduces every number in the deck against the canonical 59-bank dataset.
- `SCENARIO.md` — what you're reading.

All numbers in the deck are **engine output against the canonical 59-bank dataset** in `/home/cpo/raroc-premium-data/premium_banks.json`, not estimates.

**Canonical product numbers (verified):**
- 59 bank profiles (4 free + 55 premium)
- 26 countries (EU, UK, US, APAC, LatAm, Gulf)
- EUR 49 / year for the Pro tier

---

## The scenario in one paragraph

**Nordwind Industries GmbH** — German Mittelstand, BBB+ / Baa1, EUR 820 m revenue, machinery. Last quarter, **Sabine** (the CFO) renewed her **EUR 50 m / 5-year revolving credit facility** with BNP Paribas at **150 bp + 20 bp commitment + EUR 50 k participation**. Average drawn EUR 35 m, parent company guarantees 50 % of the exposure. She signed it without a model of what BNP could actually accept.

Three weeks later, her advisor showed her OpenRAROC. Today's the post-mortem on what she could have asked for — and the playbook for the next renewal.

That single deal carries the whole talk through three chapters: *what BNP really sees → how BNP ranks vs alternatives → what Sabine brings to her next meeting.*

---

## Slide-by-slide talk track

### Slide 1 — Title (~30 s)
> "Your bank quotes you a number. Until today, you couldn't tell whether it was generous, fair, or daylight robbery. After this demo, you'll know — and so will your next quote."

Stop. Let it land. Don't introduce yourself for 10 seconds.

Don't say "we're going to teach you about RAROC" — patronising for the half of the room that already knows. Just demonstrate.

### Slide 2 — The opacity problem (~75 s)
Two columns side by side. **Left** = what's on the term sheet ("150 over EURIBOR, subject to credit committee, market conditions"). **Right** = what the RM defends internally (K, FPE, EAD, EL, funding cost, output floor, hurdle, CTI, ETR).

The asymmetry is the whole product opportunity.

Land on the bottom callout:
> "30 basis points on a EUR 50 million facility is EUR 750,000 over a 5-year tenor. That's a senior hire. That's a software stack. That's the dividend your CEO didn't get to announce."

If an advisor asks "do treasurers really not see this?":
> "They see the price. They've never had the model behind it. We did the model."

### Slide 3 — What OpenRAROC is (~60 s)
Four KPI tiles — skim in 15 seconds, anchor on **EUR 49 / year**.

Then the two columns at the bottom: **For your company / For your firm**. This split sets up the Door A / Door B closing on slide 12 — call it out so the audience sees the structure coming.

### Slide 4 — Methodology (~75 s)
The credibility slide, *for the buyer*. Not "our model is right vs your bank's model" — but "the math you bring into the meeting is auditable end to end".

Land on the highlighted row:
> "Every input in our model comes from your bank's own annual report. Your RM cannot say 'your tool is wrong' without first saying 'our published filings are wrong'. They won't."

Define each acronym in one sentence as you read the row — most of the audience will know PD/LGD/EAD; some won't.

### Slide 5 — Meet Sabine (~45 s)
Don't read the cards. Just point.

Hook (memorise):
> "Nordwind's CFO, Sabine, got a 150 bp quote from her BNP RM last quarter. She said yes, signed it. Three weeks later her advisor showed her this tool. Today's the post-mortem on what she could have asked for. And what she's going to ask for next time."

### Slide 6 — Chapter 1: what BNP really sees (~120 s)
Switch to the live tool here if possible. Open http://localhost:8000 (or openraroc.com), pre-fill the deal, hit *Calculate*.

Walk down the breakdown line by line. Define the acronyms inline:
- *Revenue* — what BNP earns annually from spread + fees.
- *Operating cost* — BNP's cost to run the relationship, ~40% of revenue.
- *EAD* — exposure at default. Drawn + 75% of undrawn.
- *PD* — probability of default. 0.10% for BBB+/Baa1.
- *PD adjusted for GRR* — after the parent guarantee absorbs half the loss.
- *K* — capital % BNP holds against the exposure.
- *FPE* — economic capital. EAD × K. €1.97M of BNP equity locked up.
- *EL* — expected annual loss. Tiny for an investment-grade name.
- *RAROC* — the answer. **12.52%**.

Land on the right-hand panel:
> "BNP is comfortable. RAROC of 12.52% sits right above the typical 12% hurdle. The number Sabine never knew: BNP has roughly EUR 23,000 of margin per year they could give back and still hit hurdle. They were never going to volunteer that."

### Slide 7 — Chapter 1 commentary (~75 s)
The "what Sabine sends to her RM next week" slide. Four sentences, each one a lever. Read them out loud, pause after each. Don't ad-lib past the four — they're calibrated.

### Slide 8 — Chapter 2: how BNP ranks (~120 s)
Live: switch to the **Bank Comparison** tab, tick all 8 banks, hit *Compare*.

Three levels to land in order:
1. "JP Morgan would do this deal at 123 bp. BNP needs 143. Same risk to Nordwind. That's a 20 basis point gap that's now visible to you."
2. "Deutsche Bank can't do it under 156 — they're losing money below that. So when Deutsche says 'best we can do is 145', they're being generous, not stingy."
3. "Sabine doesn't have to switch banks. She has to walk into the room with the chart on slide 8."

Tone: don't trash a bank by name. JPM's high-RAROC isn't them being cheap, it's tax + scale. Deutsche's high min-spread isn't incompetence, it's CTI + funding cost. Frame the dispersion as structural.

### Slide 9 — Chapter 2: where the gap comes from (~75 s)
Three columns: **CTI / Tax / Output floor**. Each column ends with the line Sabine puts in her email:
- *"I'm paying for your inefficiency."* (CTI)
- *"Have you considered which entity books this deal?"* (Tax)
- *"What floor are you currently applying to my exposure?"* (Output floor)

The pivot:
> "You're not negotiating the math. You're using the math to negotiate."

### Slide 10 — Chapter 3: the negotiation move (~90 s)
Live: same deal, hit **Solve minimum spread**, target = 12%. Engine returns **143 bp**.

Punchline (memorise):
> "Sabine walks into the next meeting with this table on her iPad. Her opening line is 'I know your floor on this deal is 143. Let's start there'. The negotiation that used to take three calls now takes thirty seconds."

If you have a tablet, mirror the live tool. The visual of the table appearing on demand sells the moment.

### Slide 11 — Chapter 3: the three outcomes (~75 s)
Walk left to right. The killer point is that **Sabine wins all three**:
1. BNP matches at 143 → €23k/year × 5 = €116k locked in.
2. BNP bundles at 135 + cross-sell concession → ~€75k/year + locked-in FX. Best.
3. BNP holds at 150 → Sabine takes the file to ING. BNP loses the renewal.

Today she has zero of these levers. After OpenRAROC she has all three.

Land on:
> "The deal still gets done. The question is whether you're driving the conversation or being driven by it."

### Slide 12 — Two doors (~75 s)
Don't pitch — just open the doors.

**Door A — companies:**
- Free tier: 4 banks, full calculator, comparison, sensitivity. Enough for one facility.
- Pro: EUR 49/year, all 59 banks, portfolio optimizer, PDF reports, API access.
- Onboarding: 30 minutes, no procurement cycle at this price.

**Door B — partners:**
- Referral (20% recurring) → white-label (annual licence) → OEM (API/MCP embed). Three flavours of the same engine.
- Suggested path: start as referrer this quarter, upgrade to white-label when you have 5+ active clients.

Closing line (memorise):
> "Two days from now, half of you will have run a deal through the free tier on a real facility. One in ten of you will be on Pro within a month. Three of you will email me about the partner program. That's the predictable distribution. The unpredictable part is which three."

Then pause. Take questions. Have openraroc.com open behind you.

---

## Live demo prep — what to set up before the meeting

### One-time
```bash
cd /home/cpo/raroc
pip install scipy click rich fastapi uvicorn python-pptx
```

### Five minutes before the call
```bash
cd /home/cpo/raroc
RAROC_PREMIUM_BANKS=/home/cpo/raroc-premium-data/premium_banks.json \
  python3 serve.py
```

Open in browser: http://localhost:8000

Pre-fill the inputs (saves 30 seconds of awkward typing on stage):
- Product: **Medium/Long-term credit**
- Avg drawn: **35,000,000**
- Avg volume: **50,000,000**
- Spread: **0.015**
- Commitment fee: **0.002**
- Participation fee: **50,000**
- Rating: **Baa1**
- Maturity: **60**
- GRR: **0.5**
- Confirmed: **Yes**

Have a second tab open on **Bank Comparison** with all 8 banks pre-selected.

### Backup plan if no internet
```bash
cd /home/cpo/raroc
RAROC_PREMIUM_BANKS=/home/cpo/raroc-premium-data/premium_banks.json \
  PYTHONPATH=/home/cpo/raroc \
  python3 demo_deck/demo_numbers.py
```
Reproduces the exact terminal output for all three chapters. Project the terminal if the web app is unavailable.

---

## Likely questions and how to answer

**Q. "Isn't this just going to make my bank angry?"** *(treasurer)*
> Not if you use it well. The point is to walk into the meeting prepared, not to lecture the RM on their own model. Most RMs respect a counterparty who has done the work — it shortens the negotiation, which they want too.

**Q. "How accurate is this compared to what my bank actually computes?"** *(treasurer)*
> Within a few basis points on RAROC, on the deals we've benchmarked. The remaining gap is the bank's funding spread (which they don't publish per-product) and any deal-specific structuring. Both are addressable in the conversation, not at the calculator.

**Q. "What about banks that haven't disclosed their CR6 table?"** *(advisor)*
> We don't include them. Every bank in the dataset has a HIGH-confidence Pillar 3 source, listed on the methodology page. That's why coverage is 59 banks rather than 200.

**Q. "Cost-to-income from the 10-K is bank-wide, not corporate-banking-specific."** *(savvy advisor)*
> Correct. We use it as a proxy. Segmental CTI from divisional disclosures is on the roadmap. For most negotiations, the bank-wide number is directionally right and is the number your RM will defend on a call.

**Q. "Won't every CFO doing this just commoditise pricing?"** *(advisor with skin in the game)*
> Pricing dispersion is what we're exposing, not creating. Banks that win on bundle, on speed, on relationship will keep winning. Banks that hide behind opacity will lose share. The tool actually makes the bundle case *easier* to defend — that's the third negotiation outcome on slide 11.

**Q. "What's the white-label cost?"** *(advisor)*
> Tiered by client volume. Cheaper than building it; we have a one-pager for follow-up.

**Q. "Is this just for European banks?"** *(treasurer with US/Asian exposure)*
> No — 26 countries, 59 banks. US (JPM, BofA, GS, MS, WFC, Citi, BNY), Chinese (ICBC, CCB, BoC), Japanese (MUFG, SMBC, Mizuho), Australia, Canada, India, Gulf, LatAm. Treasurers running multi-currency wallets compare your bank against an Asian or Gulf relationship — they couldn't before.

**Q. "What about IRB advanced vs foundation?"** *(genuinely technical attendee — rare)*
> Engine supports both. Bank profile carries the approach. Most large EU banks are A-IRB on corporate; US banks under Basel III endgame are mostly standardised; profile records which.

**Q. "Can I plug this into my treasury management system?"** *(treasurer or partner)*
> Yes — REST API on the Pro tier, MCP server for AI-assistant access. White-label embeds run inside your existing portal.

---

## What NOT to say

- Don't pitch this as a banking-industry tool — it isn't. It's a buyer-side product.
- Don't trash specific banks by name. Frame dispersion as structural.
- Don't quote a hurdle rate as if it were universal. 12 % is a Western European mid-cycle proxy; ranges 9–15 %.
- Don't get drawn into a methodology debate. The audience can't follow it; the partner audience doesn't care; the technical audience already trusts you if you got to slide 4.
- Don't say "we'll save you money" — say "you'll know how much money was on the table". Lets the audience do the math themselves; more credible.

---

## After the demo — what to leave behind

1. The PPTX (`openraroc_demo.pptx`).
2. Free-trial link to openraroc.com.
3. For partners: one-pager on referral / white-label / OEM economics.
4. Your contact card.

The follow-up email lead is always the same:
> *"You asked about [their bank, or a specific facility]. I ran the numbers post-call. RAROC came out at X.XX %, min spread Y bp. Happy to share the workings."*

That email gets opened. That email books the second meeting.
