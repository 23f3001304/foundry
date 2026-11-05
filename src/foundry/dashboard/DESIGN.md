# The dashboard's design system

Everything visible comes from `static/style.css`, the macros in `templates/_ui.html`, the shapes in `shapes.py` and the charts in `charts.py`. `tests/test_dashboard_design.py` fails when the rules below are broken.

## Rules

- **Colour is the system, and each colour has a job.** Five gradient families, written down below. Neutrals carry everything else, so a colour on a page always means something.
- **One saturated moment a page.** The overview has its hero shape, and a job's page has its banner when something happened. The rest of the page stays quiet so that one thing lands. A job that is just running has no banner, because nothing happened.
- **A clear order on every page.** Title, then tabs, then state pills, then the big thing, then the charts, then the detail. Hairlines before boxes: a table has no card round it, and a section is a row with a chevron.
- **Colour is only written in the tokens block.** A rule names a token, and a component reads `--fam-grad`, `--fam-dot`, `--fam-text`, `--fam-wash` and `--fam-line` from whichever family it sits in. It never names a colour.
- **The 4px rule.** Every padding, margin, gap, height, radius and offset is a token. Only 1px borders and the 2px focus ring are off the grid.
- **Everything leads somewhere.** A figure, a "needs you" row, a stage and a job row each link to the list or the place where it can be acted on, and each answers the mouse and the press.
- **Every empty or result page offers the next step.**
- **No scripts and no inline styles.** The Content-Security-Policy stays as it is in `app.py`. Fonts, pictures and icons come from `/static`, and shapes and charts are drawn on the server.
- **Words carry the meaning.** A mark, a shape, a sprite or a chart never says something the text beside it doesn't. Shapes and sprites are hidden from screen readers, and a chart says what it shows in words.
- **Dark first.** Dark is what gets designed and judged. Light follows the system setting and keeps working: its block changes the neutrals, the soft fills and the marks (`--lime-mark` and the rest, for dots and chart lines, which a bright hue can't carry on white), and the gradients and the big shapes stay as they are.

## The families

Each runs from a bright hue to a deeper one and is shown as a gradient, a dot, a soft fill with matching words, or a chart line. Hues are our own and are picked to sit around the logo's lime.

| Family | Tokens | What it means |
|---|---|---|
| Lime | `--lime-*` | Good and finished: delivered, the primary action, the Work group, and the logo's own colour |
| Ember | `--ember-*`, `--ember-deep-*` | Needs someone: a stuck job or a card waiting on this login. Nothing else may use it |
| Azure | `--azure-*`, `--azure-deep-*` | Foundry at work: being made, cards opening, files, and the Setup group |
| Orchid | `--orchid-*`, `--orchid-deep-*` | Being checked: the reviewer and sign-off |
| Sun | `--sun-*` | With the people: the brief and the inputs being collected, and the Records group |

`queries.py` ties each stage to its family in `STEP_FAMILIES`, and `family_of` says stuck is ember and done is lime whatever the stage. `.fam-lime` and the rest set a family on an element, and the state classes `.working`, `.waiting`, `.done`, `.idle` and `.stuck` bring one for a status mark that has none. A family used for a banner has a deep version, so white words on it pass AA. Lime and sun are too bright for that, so a banner in either has dark words and a dark button.

Ember is not used for a fall in a number. A delta that moved is green, one that didn't is quiet, and ember only appears on a chart when the job has stopped.

## Shapes

Drawn in `shapes.py` as our own paths, in one family each. `shapes.defs()` puts every gradient on a page once and hidden, and a part names one with `fill="url(#id)"`, so no colour goes in the markup.

| Shape | Function | Where |
|---|---|---|
| Cut-out | `shapes.cut_out(family)` | The overview's hero: long curves and one sharp cusp hugging the bottom of a rounded panel, with the figures in a dark bar over it. Ember when something is stuck or waiting on this login, otherwise lime |
| Grid tile | `shapes.grid_tile(family)` | Sign-in and empty states: a family's gradient with thin dark lines, and a dark card overlapping it and running off the edge |
| Icon tile | `tile(icon, family)` | Beside a section's title, a small square in its family's gradient |

## Tokens

| Group | Values |
|---|---|
| Space | `--space-` 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 |
| Type | `--text-` / `--line-` 12/16, 14/20, 16/24, 20/28, 24/32, 32/40 |
| Radius | `--radius-` 4 (chip), 8 (control), 12 (panel), 16 (card), 24 (hero and sign-in) |
| Control height | `--control-` 32, 40 |
| Icons and sprites | `--size-` 16, 24, 32, 48, 64, 96 |
| Layout | `--gutter`, `--gap`, `--sidebar`, `--side-folded`, `--rail`, `--content`, `--measure`, `--form`, `--sign-in`, `--sign-in-art`, `--hero`, `--hero-shape`, `--col-*`, `--step`, `--tabbar` |
| Motion | `--dur-fast` 120ms, `--dur-base` 200ms, `--dur-slow` 320ms, `--dur-reveal` 640ms, `--frame` 120ms, `--frame-slow` 320ms, `--ease-out` |
| Neutrals | `--paper --side --panel --sunken --hover --current --rule --rule-strong --field --ink --ink-soft --ink-faint`, leaning very slightly toward the logo's olive |
| Accent and focus | `--primary --primary-hover --primary-ink --focus` |
| The dark bar and words on colour | `--bar --bar-hover --bar-rule --bar-ink --bar-soft --on-bright --on-deep --grid-line` |
| Gradients | `--grad-lime --grad-ember --grad-azure --grad-orchid --grad-sun --grad-none --deep-ember --deep-orchid --deep-azure`. A gradient is only written here |

## Components

Each has one definition, with its states: rest, hover, focus (one shared ring), active and disabled where it can be.

| Component | Class | Notes |
|---|---|---|
| Page title | `page_title()`, `.title` | A breadcrumb in the h1: the way back is muted and where you are is not |
| Job tabs | `job_tabs()`, `.tabs` | Underlined. Job, Timeline, Files, and Chain once something is flagged |
| State pills | `.state-pills`, `.state-pill` | Under the title: a coloured dot, and the current one outlined |
| Hero | `.hero` | The overview's one loud thing, with `.hero-bar` and `.figure` inside it |
| Banner | `.banner` | The job page's one loud thing, one at a time. It says what happened, and its one button goes to where it can be dealt with. What it says isn't said again below it |
| Chart panel | `.chart-panel`, `.chart-cell` | One bordered panel cut by hairlines into cells, each with a title and a delta. A cell with nothing to draw says so and has no delta, and a job with nothing to chart has no cells |
| Delta | `.delta` | A soft chip beside a chart's title. `.delta-good`, `.delta-flat`, `.delta-stuck` |
| Legend | `legend()`, `.legend` | Diamonds in the line's own colour, with mono values |
| Icon tile | `tile()`, `.tile` | One family's gradient beside a section title |
| Figure | `.figure` | Label, number and an arrow, on the hero's dark bar. The whole figure is the link |
| Pill | `.pill` | A short fact or a count. `.pill-needs` needs you, `.pill-stuck` stuck |
| Chip | `.chip-link` | A filter, kept in the address, with a dot in the stage's family |
| Button | `button` `.button` | `.primary`, `.danger` (inverted, not red), `.quiet`, `.button-wide` |
| Nav item | `.nav-item` `.tab` | Side bar and bottom bar. Where you are is a soft filled row |
| Switcher | `switcher()`, `.switcher` | Which business, built with details |
| Table | `table.list` | No card round it, hairlines only, small grey heads, and a row turns into a short block on a phone |
| Section | `.fold` | A row with a chevron and a tile, built with details |
| Rail | `.rail`, `.facts` | Label and value pairs beside a job, then its stages |
| Stepper | `.stepper` `.stepper-named` | The stage it is at wears its state's shape. In the rail each stage says its status |
| Progress bar | `charts.meter` | Fills on load |
| Status mark | `.stage` with `.done .working .waiting .idle .stuck` | A soft fill and matching words, and a dot, diamond, ring, dash or square. Drawn with borders alone |
| Alert | `.alert` `.alert-done` | Marked with `!` and a border |
| Avatar | `avatar()`, `.avatar` | Initials in a quiet circle. No colour, because no person is ever ranked or marked |
| Empty state | `empty_state()` | A grid tile, a character at rest, what is true and the next step |
| Sprite | `sprite()` | See below |

## Navigation

The side bar has the logo and a fold control, then the business, then Overview and Responses, then the groups Work (Jobs, Generated work), Records (Action log) and Setup (Connections, Data), each built with details, then the person and sign out. There is no top bar. The fold lasts until the next page, because keeping it would need a script or a cookie.

From 1024px down the logo and the business stay along the top, and a bar along the bottom has Overview, Jobs, Responses, Generated work and More. Badges count across every business the login has: cards waiting on it, and stuck jobs. A login with several businesses sees one overview at a time, and the first one until it chooses.

The logo is `static/logo.svg` and the full word is `static/wordmark.svg`, so changing either is one file.

## Charts

Every number comes from `queries.py`, scoped to what the login may see. No chart ranks or compares people.

- **A job's three charts** are running counts from its own log at twelve even points of its life. The band is the real gap between two lines, for example asked for and in. It is not a confidence band.
- **The overview's charts** are per day over the last 14 days, and the fill under a line is only a fade.
- **Lines** are saturated, in the family of what they count, with a soft fill, a dashed line at zero and a diamond at the end. Bars and meters use a family's bright hue.

## Characters

Sheets are in `static/sprites`, built by `tools/make_sprites.py` from `assets/team` and `stickers/base`. Frame one of a sheet is the still, so a page at rest or with motion turned off shows the still. Moves are whole sprite pixels on hard steps.

One character per context: on the overview's hero, at the stage a job is at in its rail, in an empty state and at sign-in. A figure, a table row and a chart carry none.

| State | Character | Reaction |
|---|---|---|
| Brief | Apprentice | Still |
| Collecting, or a card waiting | Smith with a question | Foot taps twice |
| Being made | Designer | Still |
| Review | Reviewer | Still |
| Sign-off | Smith | Still |
| Approved, being delivered | Smith on the way | Still |
| Delivered | Smith with confetti | A hop, twice |
| Stuck | Smith with a stop sign | Shakes twice |
| Empty page | Any of the team | Blinks and breathes, three times, then rests |
| Sign-in | Smith | Waves twice |
| A button's result came back done, or a file was saved | Smith with a tick | Nods |
| Under the mouse, on the hero, a stage or an empty state | Whoever is there | A small hop |

A reaction belongs to a job or a page, never to a person, and a character never stands beside someone's name. Keep to a few things moving at once, nothing moving over data, and no loop that doesn't end.

## Motion

A chart's line reveals from the left, bars and meters grow, numbers rise a little, the hero's shape swells once, and a row or a button answers in `--dur-fast`. With motion turned off, nothing moves and every character stands at its still.
