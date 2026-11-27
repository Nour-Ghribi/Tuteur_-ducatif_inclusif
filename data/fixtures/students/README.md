# Student History Fixtures

Anonymised, synthetic student interaction data used for:
- Platform demonstration (showing what the system looks like after real use)
- RL policy warm-start (seeding the adaptive model before real student data)
- Evaluation benchmark (measuring recommendation quality offline)
- Integration tests (testing the full pipeline with realistic data)

## Files

| File | Description |
|---|---|
| `profiles.json` | 5 synthetic student profiles with varied needs and school levels |
| `sessions.json` | 12 learning sessions across the 5 students |
| `interactions.json` | ~180 answer attempts with outcomes, timing and skill labels |
| `engagement_snapshots.json` | Pre-computed engagement scores for each student |
| `badges_earned.json` | Badges awarded based on the interaction history |

## Student profiles

| ID | Age group | School level | Cognitive need | Vision | Language |
|---|---|---|---|---|---|
| `student-demo-1` | middle | middle | none | none | fr |
| `student-demo-2` | primary | primary | dyslexia | none | fr |
| `student-demo-3` | high | high | none | protanopia | ar |
| `student-demo-4` | university | university | adhd | none | en |
| `student-demo-5` | middle | middle | autism | low_vision | fr |

## Privacy

All data is **fully synthetic**. No real person's data was used.
Subject refs are pseudonymous identifiers. The fixture generator seed
is fixed (seed=42) for reproducibility.
