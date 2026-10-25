# Streetwise brand

## Essence

Streetwise is navigation for people who think. It does not tell you a street is safe or dangerous. It shows you what is on it at the minute you get there, and why the route it picked is better.

**Tagline:** Walk like you know.
**Short pitch:** Maps pick the shortest path. Streetwise scores every block by what is open, lit and reachable when you pass it.
**Name:** Street-smart. The product is wise about the street, not afraid of it.

## Personality

| Is | Is not |
| --- | --- |
| Calm, precise, quietly confident | Alarmist, dramatic, cute |
| Shows its work | A black box that says "trust me" |
| Honest about what it does not know | Overconfident, "AI-powered" |
| About conditions on a street | About neighborhoods or who lives there |

## Voice

Plain sentences. Numbers first. One idea per line. Name the reason, not the feeling.

| Say | Never say |
| --- | --- |
| "Your usual route scores 49. I found one at 60, 1 minute longer." | "Avoid this dangerous area!" |
| "Longest stretch with nothing open: 110 m" | "Sketchy block ahead" |
| "A lamp was reported out here 3 days ago" | "Unsafe lighting" |
| "No listed hours for 63 places nearby, so this may be understated" | "100% accurate" |
| "Conditions, not a safety rating" | "The safest route" |

Rules: never use "safe", "unsafe", "dangerous" or "sketchy". Never name a neighborhood as a problem. Say when data is missing. Do not say "AI-powered"; say what the agents did.

## Logo

A lamp with a route through it. The amber disc is the lamp (what is alive on the street). The line is the walk, from a start point to a pin.

Files in `apps/web/public/brand/`:

| File | Use |
| --- | --- |
| `mark.svg` | App icon, avatar, splash. Full colour with glow, for dark backgrounds |
| `lockup.svg` | Mark plus the wordmark "Streetwise". Wordmark is live text in Bricolage Grotesque 800. Outline it in Figma before print |
| `mark-mono-dark.svg` | One colour on dark |
| `mark-mono-light.svg` | One colour on light |

Wordmark: Bricolage Grotesque ExtraBold, tracking -1.5%, "Street" in Moon, "wise" in Lamp.
Clear space: the height of the lamp disc on every side. Minimum size: 24 px for the mark, 96 px wide for the lockup.
Do not: recolour the lamp, add a drop shadow to the lockup, put the glow mark on a light background (use the mono-light mark), stretch it, or rotate it.

## Colour

The product is a night product, so the brand is dark first. Amber is the one brand colour. Coral, teal and violet are signals, each with one meaning.

| Name | Hex | Meaning | On Night | Use |
| --- | --- | --- | --- | --- |
| Night | `#070B12` | Page background | n/a | Backgrounds |
| Panel | `#0D1520` | Surfaces | n/a | Cards, sheets |
| Raise | `#121C2A` | Raised surfaces | n/a | Inputs, selected rows |
| Line | `#1F2D3F` | Borders | n/a | Dividers |
| Moon | `#E8EDF3` | Primary text | 16.7:1 | Text |
| Fog | `#8FA0B3` | Secondary text | 7.4:1 | Captions, labels |
| **Lamp** | `#FFB547` | Streetwise: the brand, the recommended route, the selected state | 11.2:1 | Primary actions |
| **Ember** | `#FF6B5A` | An empty stretch, the fastest route, attention | 7.0:1 | Gaps, warnings |
| **Glow** | `#3DD6C3` | Open and lit | 10.9:1 | Places open, good segments |
| **Signal** | `#9A8CFF` | An agent is working | 7.1:1 | Agent trace, agent chips |
| Dawn | `#F2F5F7` | Light surfaces | n/a | Guardian page, print |
| Ink | `#0B1620` | Text on light | 16.7:1 on Dawn | Light mode text |
| Lamp Ink | `#9A5A00` | Amber text on light | 5.0:1 on Dawn | Lamp on light backgrounds (plain Lamp fails at 1.6:1) |

Text on a Lamp button is `#1B1203` (10.5:1). Never put colour alone carrying meaning: always pair it with a number or a word.

## Type

| Role | Font | Weights | Use |
| --- | --- | --- | --- |
| Display | Bricolage Grotesque | 700, 800 | Titles, scores, the wordmark |
| Body | IBM Plex Sans | 400, 500, 600 | Interface text |
| Data | IBM Plex Mono | 400, 500 | Times, distances, agent names, chips |

Scale: 12 caption, 14 body small, 16 body, 20 title, 28 headline, 40 display, 64 score. Scores use tabular numbers.

## Shape and space

Radius: chip 99, button 12, card 16, sheet 28. Spacing steps: 4, 8, 12, 16, 24, 32. Touch targets 44 px minimum. Cards are glass on Night: a 1 px Line border and a faint top highlight. Glow is reserved for things that are alive: the lamp, the recommended route, an open place.

## Motion: lamplight

- **Breathe:** the lamp glow scales 0.94 to 1.04 over 4.5 s. Used on the brand mark and the walk state.
- **Draw:** a route draws from A to B in about 1.5 s, then light flows along it.
- **Count:** scores count up with a cubic ease-out in about 1 s.
- **Pop:** open places appear one after another, 55 ms apart.
- **Respect reduced motion:** every animation has a still state that carries the same information.

## The score, in brand terms

Name: **Streetwise Score** (at night: Night Walk Score). Always shown out of 100 with the breakdown one tap away. Always labelled "conditions, not a safety rating". Always compared to typical walks in the same area at the same hour.

## The crew (agents)

All agents use Signal violet. They speak in first person, short, and say what they did.

| Agent | Job | Sounds like |
| --- | --- | --- |
| Scout | Plans and re-scores routes | "Streetwise route scores 69 against 55, 1.1 minutes longer." |
| Place agents | Shops declare live hours | "Peet's Coffee will stay open until 1 AM." |
| Watcher | Follows the walk | "Stopped near an open shop. Staying quiet." |
| Rescuer | Runs the alert ladder | "Guardian link opened. Handoff packet drafted. No call to 911." |
| Reporter | Files what the walk found | "Draft 311 report saved. Nothing submitted." |
| Night Auditor | Finds stale data overnight | "491 places have no listed hours." |

## Applications

App icon: `mark.svg` on Night (PNG exports are generated in `apps/web/public`). Devpost banner and slides: Night background, the lockup, one number in Display. Social avatar: the mark. Print: use Dawn, Ink and Lamp Ink.

> Update: the team Figma file supersedes this guide. Its accent is indigo with agent mascots ("The Night Shift"), not amber. Use `apps/web/src/design/tokens.css` for current values.
