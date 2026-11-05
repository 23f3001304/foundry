# The dashboard's design system

Everything visible comes from `static/style.css`, the macros in `templates/_ui.html` and the charts in `charts.py`. `tests/test_dashboard_design.py` fails when the rules below are broken.

## Rules

- **Three kinds of colour.** Neutrals, one accent (lime) and one red. Red means stuck and nothing else: a problem or a destructive button is marked by its shape and its contrast. Waiting, working and idle are neutrals told apart by shape.
- **Colour is only written in the tokens block.** Charts use neutrals and the accent only. The characters bring the warmth, so the interface stays quiet around them.
- **The 4px rule.** Every padding, margin, gap, height, radius and offset is a token. Only 1px borders and the 2px focus ring are off the grid.
- **One column grid.** Twelve columns with one gap. A row spans 3, 4, 6, 8 or 12 of them, so edges line up across rows. Cards in a row are equally tall, and their last line sits on one baseline.
- **Everything leads somewhere.** A figure, a "needs you" row, a stage and a job row each link to the list or the place where it can be acted on. A card that links looks like one: underlined words or an arrow, and a response on hover and press.
- **Every empty or result page offers the next step.**
- **No scripts and no inline styles.** The Content-Security-Policy stays as it is in `app.py`. Fonts, pictures and icons come from `/static`.
- **Words carry the meaning.** A mark, a sprite or a chart never says something the text beside it doesn't. Sprites are hidden from screen readers.

## Tokens

| Group | Values |
|---|---|
| Space | `--space-` 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 |
| Type | `--text-` / `--line-` 12/16, 14/20, 16/24, 20/28, 24/32, 32/40 |
| Radius | `--radius-` 4 (pill), 8 (control), 12 (card), 16 (sign-in) |
| Control height | `--control-` 32, 40 |
| Icons and sprites | `--size-` 16, 24, 32, 48, 64, 96 |
| Layout | `--gutter`, `--gap`, `--sidebar`, `--content`, `--measure`, `--form`, `--col-*`, `--step`, `--tabbar`, `--art-*` |
| Motion | `--dur-fast` 120ms, `--dur-base` 200ms, `--dur-slow` 320ms, `--frame` 120ms, `--frame-slow` 320ms, `--ease-out` |
| Colour | `--paper --side --panel --sunken --hover --current --rule --rule-strong --field --ink --ink-soft --ink-faint --primary --primary-hover --primary-ink --bad --bad-wash --bad-rule` |

## Components

Each has one definition, with its states: rest, hover, focus (one shared ring), active and disabled where it can be.

| Component | Class | Notes |
|---|---|---|
| Card | `.card` `.card-head` `.card-foot` | Opaque, so art behind it can't reach the data |
| Figure | `.figure` | Label, number, note, optional chart and sprite, then where it leads. The whole card is the link |
| Pill | `.pill` | A short fact or a count. `.pill-accent` needs you, `.pill-stuck` stuck |
| Chip | `.chip-link` | A filter or a choice of business, kept in the address |
| Button | `button` `.button` | `.primary`, `.danger` (inverted, not red), `.quiet`, `.button-wide` |
| Nav item | `.nav-item` `.tab` | Side bar and bottom bar |
| Table row | `table.list` | Turns into a short block on a phone |
| Stepper | `.stepper` `.stepper-named` | The stage it is at wears its state's shape |
| Progress bar | `charts.meter` | Fills on load |
| Status mark | `.stage` with `.done .working .waiting .idle .stuck` | Dot, diamond, ring, dash, square. Drawn with borders alone |
| Alert | `.alert` `.alert-done` | Marked with `!` and a border, not with red |
| Empty state | `empty_state()` | A character at rest, what is true, the next step |
| Sprite | `sprite()` | See below |
| Breadcrumbs | `crumbs()` | On every detail page |
| Job tabs | `job_tabs()` | Job, Timeline, Files, and Chain once something is flagged |

## Navigation

Work (Overview, Jobs, Responses, Generated work), Records (Action log), Setup (Connections, Data). A side bar from 1025px, and below that a bar along the bottom with the four Work pages and More. Badges count across every business the login has: cards waiting beside Responses, stuck jobs beside Jobs. With several businesses, Overview and Jobs show a row of chips, and `?business=` narrows them.

## Characters

Sheets are in `static/sprites`, built by `tools/make_sprites.py` from `assets/team` and `stickers/base`. Frame one of a sheet is the still, so a page at rest or with motion turned off shows the still. Moves are whole sprite pixels on hard steps.

| State | Character | Reaction |
|---|---|---|
| Brief | Apprentice | Still |
| Collecting, or a card waiting | Smith with a question | Foot taps twice |
| Being made | Designer | Still |
| Review | Reviewer | Still |
| Sign-off | Smith | Still |
| Approved, being delivered | Smith on the way | Still |
| Delivered | Smith with confetti | A hop, twice |
| Stuck | Smith with a stop sign | Shakes twice, for the first three stuck jobs on a page |
| Empty page | Any of the team | Blinks and breathes, three times, then rests |
| Sign-in | Smith | Waves twice |
| A button's result came back done, or a file was saved | Smith with a tick | Nods |
| Under the mouse, on a job or a card that links | Whoever is there | A small hop |

A reaction belongs to a job or a page, never to a person, and a character never stands beside someone's name. Keep to a few things moving at once, nothing moving over data, and no loop that doesn't end.
