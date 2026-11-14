# 🎧 Model Card: VibeFinder 1.0

**Author:** Joshua Lookshin (z23411056)

## 1. Model Name

**VibeFinder 1.0**, a content-based music recommender simulation.

---

## 2. Intended Use

**Goal / task:** Given a listener's taste profile (favorite genre, favorite mood, target
energy, and optional extras), VibeFinder suggests the top 5 songs from a small catalog and
explains why each one was picked.

**Intended use:**

- Classroom exploration of how recommenders turn data into rankings.
- Experimenting with weights, scoring modes, and diversity rules to see how results change.
- Showing why a song was picked through its list of reasons.

**Assumptions about the user:** They can describe their taste with one genre, one mood,
and a target energy level, and their taste doesn't change with time of day or activity.

**Not intended for:**

- Real users or a real product. The catalog is 20 made-up songs.
- Judging the quality of an artist or genre. A low score only means "not similar to this
  profile."
- Any decision that matters (ads, payments to artists, content moderation).
- Users whose taste can't be described with these labels. It has no lyrics, language,
  culture, or listening history.

---

## 3. How the Model Works

Think of it as a judge with a checklist who looks at every song one at a time:

1. **Right genre?** Big bonus (+2 points).
2. **Right mood?** Smaller bonus (+1 point).
3. **How close is the energy?** Up to +1.5 points. A perfect match gets all of it, and a
   song gets fewer points the further it is from the target, *in either direction*. A user
   who wants calm music isn't rewarded with the loudest song.
4. **Acoustic or not?** Up to +0.5 depending on whether the user likes acoustic sounds.
5. **Extras, only if the user sets them:** closeness to a target valence (happiness),
   danceability, tempo, popularity, instrumentalness, or speechiness (up to +0.5 each),
   shared detailed mood tags like "nostalgic" (+0.5 each, max +1.0), and the user's favorite
   decade (+0.5, or +0.25 for the decade next to it).

The points are added up, every song is sorted from highest to lowest, and the top 5 are
shown with the list of reasons.

**Changes from the starter logic:** The starter had no scoring at all. I added the full
checklist above, five new song attributes, switchable **scoring modes** (genre-first,
mood-first, energy-focused, and the weight-shift experiment), an optional **diversity
penalty** that subtracts points when an artist (−1.0) or genre (−0.5) is already in the
list, and a formatted results table.

---

## 4. Data

- **20 songs** in `data/songs.csv`. The starter had 10, and I added 10.
- **16 genres:** pop, lofi (3 songs each), and one song each for rock, ambient, jazz,
  synthwave, indie pop, hip hop, classical, metal, country, r&b, edm, folk, reggae, and
  blues.
- **14 moods:** chill, happy, intense, relaxed, sad, moody, focused, confident, peaceful,
  aggressive, nostalgic, romantic, euphoric, and melancholy.
- **Features:** energy, tempo, valence, danceability, acousticness, plus five I added:
  popularity, release decade, detailed mood tags, instrumentalness, and speechiness.
- **What's missing:** lyrics, language, artist background, real listening data (plays,
  skips, likes), and most of the world's genres (Latin, Afrobeats, K-pop, and others). The
  numbers are hand-made estimates, not measurements, so they reflect my idea of what a song
  "feels" like.

---

## 5. Strengths

- **Clear-cut profiles work well.** Chill Lofi, Deep Intense Rock, and Nostalgic Night Owl
  all put a near-perfect song at #1 with a big lead.
- **Every result is explained.** The reasons add up exactly to the score, so it's easy to
  see *why* a song ranked where it did, and easy to spot when the logic is wrong.
- **Closeness scoring captures "vibe."** Two profiles with opposite energy (lofi vs.
  high-energy pop) got completely different lists, and low-energy listeners weren't pushed
  toward loud songs.
- **Good "same vibe, different genre" picks.** Chill Lofi's #4 and #5 (ambient and jazz)
  and the night owl's tag-based picks felt like songs I'd actually want next.
- **Easy to experiment with.** Swapping modes or turning on diversity takes one
  command-line flag, with no code changes.

---

## 6. Limitations and Bias

**Main weakness: high-energy songs crowd every list.** Energy is the only rule that gives
points to *every* song, and most of my profiles asked for high energy (0.8–0.95). Four of
the 20 songs have energy of 0.9 or higher, so they keep collecting about 1.4–1.5 points
even when their genre and mood are wrong. *Gym Hero* showed up in the top 5 for 6 of the 9
non-empty profiles, including Deep Intense Rock, Sad but Hyped, and Acoustic Headbanger.
Quiet songs like *Harbor Lullaby* (folk, energy 0.30) and *Moonlit Sonata Study*
(classical, energy 0.22) almost never appear unless the user asks for that exact genre. In
effect, the system has a filter bubble that favors loud, mainstream-sounding tracks.

Other limitations I found:

- **Exact text matching:** "indie pop" gets no credit for "pop", and "melancholy" gets no
  credit for "sad". *Harbor Lullaby* never made any top 5, even for the sad listener.
- **Uneven catalog:** pop and lofi have 3 songs each, but 14 genres have only one. Fans of
  rare genres get one real match and then filler.
- **Genre can override what the user said they want:** For "Sad but Hyped," the only edm
  song ranked #1 even though it is *euphoric*, the opposite of sad.
- **Weak features stay weak:** The acoustic preference is worth 0.5 at most. For the metal
  fan who likes acoustic music it added only +0.01 to +0.09, so it changed nothing.
- **No input checking:** An energy target of 1.5 or an empty profile still produces a
  confident-looking top 5.

---

## 7. Evaluation

**Profiles tested** (all defined in `src/main.py`):

| Profile | Genre | Mood | Energy | Extras |
| --- | --- | --- | --- | --- |
| Default Pop / Happy | pop | happy | 0.80 | none |
| High-Energy Pop | pop | intense | 0.90 | not acoustic, danceability 0.85 |
| Chill Lofi | lofi | chill | 0.35 | acoustic, instrumentalness 0.85 |
| Deep Intense Rock | rock | intense | 0.92 | not acoustic, tempo 150, valence 0.4 |
| Nostalgic Night Owl | synthwave | moody | 0.65 | tags nostalgic/nocturnal/dreamy, 1980s |
| Edge: Sad but Hyped | edm | sad | 0.90 | conflicting mood vs energy |
| Edge: Genre Ghost | k-pop | happy | 0.70 | genre not in catalog |
| Edge: Acoustic Headbanger | metal | aggressive | 0.95 | likes acoustic |
| Edge: Out-of-Range Energy | classical | peaceful | 1.50 | invalid energy |
| Edge: No Preferences | none | none | none | empty profile |

**What I looked for:** Does #1 match all of the user's wishes? Do the next four "feel"
close? Does each reason add up to the score? Does one song keep showing up everywhere?

**Does it match my intuition?** Mostly yes for the normal profiles. Chill Lofi gave
*Library Rain*, *Midnight Coding*, and *Focus Flow*, which is exactly what I'd put on while
studying. Then it gave *Spacewalk Thoughts* (ambient) and *Coffee Shop Stories* (jazz),
which are good "same vibe, different genre" picks. Deep Intense Rock put *Storm Runner*
first with a big lead (5.89 vs 3.70), which feels right.

**Why does *Gym Hero* keep showing up for "Happy Pop"?** (in plain language) The system
gives out points like a checklist. *Gym Hero* is a pop song, so it gets the big "right
genre" bonus right away. It's also very energetic, which is close to the 0.8 energy the
happy-pop listener asked for, so it gets almost full energy points. It only misses the
"happy" checkbox, since its mood is "intense," and that box is worth less than the genre
box. So a workout song beats *Rooftop Lights*, a genuinely happy song, just because
*Rooftop Lights* is labeled "indie pop" instead of "pop."

**Comparing pairs of profiles:**

- *Pop / Happy vs High-Energy Pop:* Same genre, so both get the same three pop songs. Only
  the order flips. *Sunrise City* (happy) wins for the first and *Gym Hero* (intense) wins
  for the second, because the mood bonus moves to whichever song matches.
- *Pop / Happy vs Chill Lofi:* No overlap at all. Pop/happy pulls upbeat songs around 0.8
  energy, and Chill Lofi pulls quiet, acoustic songs around 0.35. This shows energy is
  doing real work beyond genre.
- *Pop / Happy vs Deep Intense Rock:* Only *Gym Hero* is in both lists. It's the "bridge"
  song, pop for one and intense/high-energy for the other.
- *Pop / Happy vs Nostalgic Night Owl:* No overlap. The night owl's mood tags and 1980s
  decade pull in *Night Drive Loop*, *Midnight Coding*, and *Dusty Back Roads*, which share
  "nostalgic," "nocturnal," or "dreamy" tags.
- *High-Energy Pop vs Chill Lofi:* Complete opposites. Energy 0.9 vs 0.35 and
  non-acoustic vs acoustic means the lists have nothing in common, which is what should
  happen.
- *High-Energy Pop vs Deep Intense Rock:* Big overlap (*Gym Hero*, *Storm Runner*,
  *Neon Pulse*), because both ask for "intense" and energy around 0.9. Genre decides who
  gets #1.
- *High-Energy Pop vs Nostalgic Night Owl:* No overlap. The night owl's moderate energy
  (0.65) and tags favor dreamy, older songs over loud new ones.
- *Chill Lofi vs Deep Intense Rock:* No overlap. Rock gets loud, fast, non-acoustic tracks
  and lofi gets slow acoustic ones.
- *Chill Lofi vs Nostalgic Night Owl:* *Midnight Coding* and *Coffee Shop Stories* appear
  in both. They're calm and also tagged "nocturnal"/"dreamy"/"nostalgic," so tags connect
  the two profiles even with different genres.
- *Deep Intense Rock vs Nostalgic Night Owl:* *Night Drive Loop* is in both lists. For the
  rock fan it's only #5 (filler on energy), but for the night owl it's a perfect #1.
- *Normal vs edge cases:* Genre Ghost behaves like a "mood + energy only" version of
  Pop/Happy (same happy songs, lower scores). No Preferences shows the system has no
  "I don't know" answer and returns alphabetical order.

**Experiment: weight shift (energy ×2, genre ×0.5).** Run with `--mode weight_shift`. It
made Pop/Happy *more* accurate (*Rooftop Lights* rose from #4 to #2) but made Sad but Hyped
and Deep Intense Rock *less* accurate (sad songs vanished, and a happy pop song entered the
rock list). So the change made results different, not better overall.

**Automated checks:** `pytest` runs 14 tests covering CSV loading, the closeness formula,
scoring and reasons, sort order, every scoring mode, the diversity penalty, the advanced
features, and the table formatter.

**What surprised me:** How much a single weight decides the outcome, and that a list
built from simple addition still *felt* like a real playlist for the normal profiles.

---

## 8. Future Work

1. **Fuzzy matching for genres and moods.** Treat "indie pop" as partly "pop" and "sad" as
   close to "melancholy" (for example with a small similarity table) so near-misses earn
   partial credit.
2. **Check inputs and admit uncertainty.** Clamp targets to 0–1, warn when a genre isn't in
   the catalog, and say "tell me more about your taste" instead of returning an
   alphabetical list for an empty profile.
3. **Balance the energy rule.** Give energy points only when a song also matches at least
   one label, or normalize scores, so loud songs stop showing up in every list.
4. **Add listening behavior.** Use simulated likes and skips to add a collaborative
   filtering signal, so the system can make surprising picks and not only "more of the same."
5. **Support more than one taste.** Let a profile hold several genres and moods (for
   example "rock for the gym, lofi for studying").

---

## 9. Personal Reflection

**Biggest learning moment:** Running the "Sad but Hyped" profile. I expected the system to
find some middle ground, but it put a *euphoric* edm song first just because the genre
matched. Nothing in the code was "wrong," but the weights made a choice I didn't intend.
That's when I understood that a recommender's behavior lives in its weights and data, not
only in its code, and that testing with strange profiles finds problems that normal
profiles hide.

**How simple algorithms can still "feel" like recommendations:** The whole system is
addition and sorting, yet the Chill Lofi list looked like a real study playlist, and the
night owl list connected a lofi track, a country song, and a jazz song through shared
"nostalgic" and "nocturnal" tags. A few well-chosen features and a closeness formula were
enough to make the results feel personal, which also shows how easily people could trust a
system like this more than they should.

**What I'd try next:** I'd add simulated user listening history so I could compare
content-based results with collaborative filtering side by side, and add fuzzy matching for
genres and moods. I'd also like to measure diversity directly (how many different artists
and genres show up across all users), not just eyeball it.
