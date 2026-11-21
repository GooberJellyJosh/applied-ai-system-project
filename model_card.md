# Model Card: VibeFinder 2.0

**Author:** Joshua Lookshin (z23411056)

This card covers the applied AI system built on top of my Module 3 project. The model
card for the original VibeFinder 1.0 is kept in
[docs/original_vibefinder_1_model_card.md](docs/original_vibefinder_1_model_card.md).

---

## 1. Model name

**VibeFinder 2.0**, a retrieval-augmented music assistant that plans, checks its own
work, and reports a confidence score.

---

## 2. Intended use

**Goal:** Take a plain-language request ("something mellow for late-night studying"),
look it up in a knowledge base, and return up to ten songs from a small catalog with
the reasons, the sources, and a confidence score for the answer.

**Intended for:**

- Classroom exploration of retrieval, planning, self-checking, and evaluation.
- Showing how an AI system can explain itself and say when it is unsure.
- Experimenting: editing a guide file and watching the answers change.

**Not intended for:**

- A real music product. The catalog is 20 made-up songs.
- Judging the quality of an artist, a genre, or a listener's taste.
- Any decision that matters to a person or a business.
- Requests in languages other than English, or about real songs and artists.

---

## 3. How it works

1. The request is checked. Empty, very long, or wordless input is rejected.
2. The request is compared with 80 short documents: one per song, plus guides that
   describe genres, moods, activities, and sound traits such as "no lyrics".
3. The matching guides are turned into targets. "Studying" becomes low energy, mostly
   instrumental, focused. Each target remembers which guide it came from.
4. Every song is scored with the VibeFinder 1.0 recipe, plus partial credit for related
   genres and similar moods and a bonus for matching the request's own words.
5. The assistant checks its own list. If something is wrong (for example the genre is
   not in the catalog) it changes the plan once and tries again.
6. It scores its confidence from 0 to 1 and writes a short explanation that only uses
   what it retrieved.

If nothing in the knowledge base relates to the request, it says so and recommends
nothing.

---

## 4. Data

- **Catalog:** 20 songs in `data/songs.csv`, across 16 genres and 14 moods. The numbers
  (energy, valence, and so on) are my hand-made estimates, not measurements.
- **Knowledge guides:** 60 hand-written entries in `data/knowledge/`: 22 genres (16 in
  the catalog and 6 that are not, such as k-pop and punk), 14 moods, 14 activities, and
  10 sound traits.
- **Evaluation cases:** 30 requests with expected outcomes in
  `data/evaluation_cases.json`.
- **No personal data** is collected. Requests are written to a local log file
  (`logs/vibefinder.log`) that is not committed to the repository.

All of this data was written by one person. Nothing comes from real listeners.

---

## 5. Strengths

- **It shows its evidence.** Every preference lists the guide it came from, and every
  song lists its reasons and source documents.
- **It can say no.** Off-topic requests, empty input, and requests it cannot connect to
  the knowledge base get a clear message instead of a made-up list.
- **It admits substitutions.** When asked for a genre the catalog lacks, it uses the
  closest one the guide lists and says that it did.
- **It handles what 1.0 could not.** Free text, synonyms ("mellow"), activities
  ("for the gym"), exclusions ("not country"), similar moods ("melancholy" for "sad"),
  and out-of-range numbers.
- **It is repeatable.** The same request always gives the same answer, which makes it
  possible to test.

---

## 6. Limitations and bias

**It matches words, not meaning.** The retriever only knows words that appear in the
guides. "Tunes for cleaning the house" is read as a request for house music. A request
that uses words the guides do not contain is declined even when a person would
understand it ("something for a long flight").

**The guides are my opinions.** I decided that studying means quiet instrumental music,
that a party means euphoric and danceable, and that a rainy day means melancholy. A
listener who studies to metal or relaxes to techno is treated as an exception. The
guides are also written in English from one cultural point of view. Six genres that are
missing from the catalog are mapped to a "closest" genre, so a request for k-pop or
Latin music is answered with pop. That is honest about the catalog but still flattens
those genres into whatever the catalog happens to have.

**The catalog bias from 1.0 is still there.** Fourteen genres have a single song, so a
fan of one of them gets one real match and then neighbors. High-energy songs still
collect energy points across many requests: *Gym Hero* was the top pick in 4 of the 23
answered evaluation cases.

**The "popular" and "mainstream" traits favor what is already popular.** Asking for
"popular" music pushes high-popularity songs up, which is the same feedback loop real
platforms have.

**One thing at a time.** Only one genre, one mood, and one activity can be targeted.
"Lofi for studying and rock for the gym" is answered for lofi only, with a warning.

**Negation is shallow.** "Not sad", "no country or metal", and "anything but pop" work.
Phrasings the planner does not recognize as negation do not: "I can't stand jazz" is
read as a request for jazz.

**The self-check verifies consistency, not intent.** The checks confirm that the list
matches the plan. They cannot tell that the plan misread the request. The "house" case
passes every self-check.

**Confidence is a formula.** It combines how much of the request was recognized, how
strongly the best document matched, and how well the top song fits the plan. It has
never been compared with what real listeners thought of the answers, so it should be
read as "more sure" or "less sure", not as a probability.

**The language model path is lightly tested.** The optional `--llm` writer is covered by
tests that use a stand-in client. It has not been run against the live API in this
repository, so its real-world wording quality is unmeasured.

---

## 7. Misuse and safeguards

This is a low-stakes system, but the patterns in it apply to higher-stakes ones.

| Risk | How it could happen | What the system does about it |
| --- | --- | --- |
| Treating output as authoritative | Someone reads the confident tone as fact | Every answer shows a confidence score, warnings, and its sources; low-confidence answers say "treat these picks as rough guesses" |
| Ranking manipulation | Whoever controls the catalog stuffs a song's tags with popular request words to win the wording bonus | The wording bonus is capped at 1.5 points, below a genre match, and the matched words are printed so stuffing is visible. There is no defense beyond that; the catalog is trusted |
| Biased guides | Whoever edits the guides decides what "studying" or "party" music is for everyone | Guides are plain JSON in version control, so every change is reviewable. No automatic check for bias exists |
| Prompt injection | A request contains instructions aimed at the language model | The model never receives the raw request, only the structured plan and retrieved notes. Its draft is rejected if it names a song or artist that was not recommended |
| Off-topic or abusive input | Using the assistant for unrelated tasks, or very large inputs | Requests over 300 characters are rejected; requests unrelated to the knowledge base are declined; results are limited to 10 songs |
| Private information in logs | A user types something personal and it is logged | Logs stay on the local machine and are excluded from the repository. Requests are logged as typed, so the log should be treated as sensitive |

---

## 8. Testing results

**Automated tests:** 152 of 152 pass (`python -m pytest`).

**Evaluation harness:** 28 of 30 cases pass (`python -m src.evaluate --baseline`).

| Measure | Result |
| --- | --- |
| Cases passed | 28 of 30 (93%) |
| Consistency | 30 of 30 identical on a second run |
| Average confidence on passed answers | 0.84 |
| Average confidence on failed answers | 0.51 |
| Songs-only baseline (no guides) | 16 of 30 |

| Failed case | Request | Why it failed |
| --- | --- | --- |
| `ambiguous-word` | "tunes for cleaning the house" | "house" was read as a genre. Confidence 0.42 (low) |
| `two-requests-in-one` | "lofi for studying and rock for the gym" | Only the lofi half was answered. Confidence 0.60 (medium), with a warning |

The first evaluation run passed 27 of 30. One of the three failures ("sad songs"
ranking a nostalgic song above a melancholy one) was a real ranking flaw and was fixed
by weighting similar moods by closeness. The other two are limits of the design and
are left failing on purpose, so the report stays honest.

Recorded outputs are in [assets/sample_runs/](assets/sample_runs/).

---

## 9. What surprised me during testing

- **The simple baseline beat the full system on one case.** The songs-only version
  passes the "lofi for studying and rock for the gym" case, because plain word overlap
  pulls in both lofi and rock songs. The smarter planner commits to one genre and loses
  the other. More structure made that case worse.
- **Confidence was backwards at first.** In an early run a correct artist lookup scored
  0.28 while the half-answered two-genre request scored 0.86. The formula was measuring
  how well the songs fit the plan, not whether the plan fit the request.
- **The worst failures passed every self-check.** I expected the self-check to catch
  the bad answers. It catches broken lists, but a misread request produces a perfectly
  consistent wrong answer.
- **An off-topic request got a confident answer.** "Write my essay about the day" was
  answered with rainy-day songs before the coverage rule was tightened, because "day"
  appears in two activity guides.

---

## 10. AI collaboration

*This section is for the author to complete before submission.* The assignment asks for:

1. How AI tools were used while building this project.
2. One AI suggestion that was accepted, and why.
3. One AI suggestion that was rejected or revised, and why.

---

## 11. Future work

1. **Handle more than one request in a sentence.** Split "lofi for studying and rock for
   the gym" into two plans and answer both.
2. **Tell word meanings apart.** Use sentence embeddings, or a rule that a genre word
   must sit in a genre-like position, so "cleaning the house" is not house music.
3. **Calibrate confidence.** Collect human ratings for a set of answers and fit the
   confidence formula to them.
4. **Review the guides with other people.** Ask listeners with different habits and
   backgrounds to check what each activity and mood guide assumes.
5. **Measure the language model writer.** Run the `--llm` path on the evaluation cases
   and compare its summaries with the template on accuracy and readability.
