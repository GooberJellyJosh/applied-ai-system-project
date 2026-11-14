# 🎧 Model Card: Music Recommender Simulation

## 1. Model Name  

Give your model a short, descriptive name.  
Example: **VibeFinder 1.0**  

---

## 2. Intended Use  

Describe what your recommender is designed to do and who it is for. 

Prompts:  

- What kind of recommendations does it generate  
- What assumptions does it make about the user  
- Is this for real users or classroom exploration  

---

## 3. How the Model Works  

Explain your scoring approach in simple language.  

Prompts:  

- What features of each song are used (genre, energy, mood, etc.)  
- What user preferences are considered  
- How does the model turn those into a score  
- What changes did you make from the starter logic  

Avoid code here. Pretend you are explaining the idea to a friend who does not program.

---

## 4. Data  

Describe the dataset the model uses.  

Prompts:  

- How many songs are in the catalog  
- What genres or moods are represented  
- Did you add or remove data  
- Are there parts of musical taste missing in the dataset  

---

## 5. Strengths  

Where does your system seem to work well  

Prompts:  

- User types for which it gives reasonable results  
- Any patterns you think your scoring captures correctly  
- Cases where the recommendations matched your intuition  

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

Ideas for how you would improve the model next.  

Prompts:  

- Additional features or preferences  
- Better ways to explain recommendations  
- Improving diversity among the top results  
- Handling more complex user tastes  

---

## 9. Personal Reflection  

A few sentences about your experience.  

Prompts:  

- What you learned about recommender systems  
- Something unexpected or interesting you discovered  
- How this changed the way you think about music recommendation apps  
