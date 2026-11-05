# How Foundry designs

The brand kit decides the colours, fonts, logo and voice. These rules decide what you do with them. If they clash, the kit wins.

## Start with the reader

1. Before you make anything, write one line: who looks at this, for how long, and what they must take away. Everything serves that line.
2. One idea per slide, one message per graphic. If you can't say it in a sentence, split it.
3. A title says the point, not the topic: "Office E holds more than the other four" and not "Assets by office". Only claim what the figures back.

## Hierarchy

4. Decide what is seen first. Squint at the page: the biggest, brightest thing must be the most important thing.
5. Use three sizes of type at most, and make the jumps obvious. 40 and 18 is hierarchy. 20 and 18 is a mistake.
6. The accent colour goes on the one thing that matters. When everything is lit, nothing is.

## Space and alignment

7. Empty space is part of the design. Never fill a gap because it's there.
8. Everything sits on a shared edge, and the same thing sits in the same place on every slide.
9. Show what belongs together by putting it close together, before you reach for a line or a box.

## Type and words

10. Fewer words. A slide that isn't a table holds about 30 words. Use a sentence where you'd use bullets, and never more than four bullets.
11. Get contrast from size and weight in the kit's own fonts. No sentences in capitals and no centred paragraphs.
12. Break a title where the sense breaks, and leave no single word alone on a last line.
13. Say the specific thing. Cut "elevate", "seamless", "leverage", "unlock" and anything that could be said about any company.

## Figures

14. A chart makes one point. Sort it, light the one bar that matters, label the bars directly, and drop the legend and the gridlines you don't need.
15. Bars compare, lines show change over time, and a pie is almost never the answer. When one number is the message, set that number huge and let the chart support it.
16. Show the precision that means something. A figure nobody sent is said in words, and never drawn.

## Rhythm

17. A deck is a sequence. Vary the layouts: a big number, a chart, a statement, a table. Never the same layout three times running, and let a quiet slide follow a dense one.
18. Open with the point, and end on what happens next.
19. A poster or a post has one headline that reads at thumbnail size, and one strong picture or none. Make it work at phone size first.

## Restraint

20. Every mark has to mean something. No decorative icons, drop shadows, stock clip art, gradients the kit didn't ask for, a box around everything, or a title bar on every slide.
21. One large picture beats three small ones. Generated pictures hold no words.

## Fit the brand

22. Let the kit's audience and voice set the density, scale and energy. An investment firm is quiet and exact, an agency's client can be loud, a cafe is warm and plain. If the work could belong to any other client with the logo swapped, it isn't finished.

## Colour

The kit and the tools set the actual colours. These rules are for choosing a ground, a composition and what gets lit, and for judging what you see.

23. Value does the work before hue does. Turn the page grey in your head: if the hierarchy disappears, the colours were hiding a weak layout. Fix the layout.
24. Split colour roughly 60, 30, 10: a ground, a supporting colour, and an accent that stays rare. The percentages are a habit, not a law. Some styles below break them on purpose.
25. Contrast is a requirement. Body text needs at least 4.5 to 1 against what's behind it, and large type at least 3 to 1. Light type on a mid-tone is where this fails, so check it on gold, orange and photos.
26. Neutrals carry a little of the brand's colour. A warm brand gets warm greys and off-whites, and a cool brand gets cool ones. Pure black on pure white looks harsh and unconsidered, unless the style wants that.
27. Saturated colours fight when they touch, and they vibrate when they're equal in value, like red on green. Separate them with a neutral, or change one's value.
28. On dark grounds, lower saturation and lift value. A colour that looks right on white looks dull or neon on black, and the tools lift the accent until it reads on its ground, so look at the result and choose another ground or other lit words if it still looks wrong. Avoid pure white body text on near-black when the kit offers a softer paper colour.
29. A colour means one thing throughout a piece. If amber marks the figure to look at on slide 2, it can't be decoration on slide 3. Red and green carry meaning for most readers, and colour never carries meaning alone, so label it too.
30. Warm colours come forward and cool ones recede. Use this to put a figure in front and let the rest fall back. Tints of one hue usually beat adding a new hue.

## Padding and spacing

build_deck and render_graphic set the margins, spacing and line spacing, so no maker types these numbers. Use these rules to choose a layout or a composition, to judge what you see, and to shorten the words when a page is tight.

31. Space comes from a scale, not from guessing. Use 4, 8, 12, 16, 24, 32, 48, 64, 96 on screens. On a slide 1600 wide, use multiples of 20. Two gaps that nearly match look like a mistake, so make them equal or clearly different.
32. Outer margins scale with the page: 5 to 8 percent of the short side for most work, 10 percent or more when the style is quiet. Keep them the same on every slide.
33. Inside comes before outside: the space within a group is always smaller than the space between groups. A heading sits closer to its own text than to the block above it. About twice the inner space is a good starting point between groups.
34. Padding follows size. Big type needs more air around it, and tiny labels need less. A panel's padding should be at least as large as the gap between the items inside it.
35. A button or tag has about twice as much padding at the sides as at top and bottom. When one thing nests in another, inner radius = outer radius minus the padding between them, or the corners won't look parallel.
36. Trust your eye over the box. Round shapes, pointed shapes and big letters look small or offset when measured evenly, so nudge them by a few units until they look right. Big type sits inside its box with its own built-in space, so align what the eye sees, not the box edge.
37. Line spacing falls as type grows: about 1.5 for body, 1.2 for subheads, 1.0 to 1.1 for huge headlines. Letter spacing goes tighter on large type and a little wider on tiny capitals.
38. Nothing touches an edge by accident. Either it sits clearly inside the margin or it bleeds clearly off the page. Half-touching is the commonest sign of careless work.

## Styles

Pick one style per piece before you lay anything out, say which with state_style, and commit to it. A top-tier piece is one style done fully, not four styles mixed. The kit limits the colours and fonts, and the style decides how to use them.

**Swiss, or International**
- What it is: a strict grid, one sans family, big left-aligned type, flat colour, asymmetry, and lots of space.
- Choose it for: IT firms, reports, process, product work, anything that must feel clear and trustworthy.
- Top tier means: every edge is on the grid, two or three sizes with huge jumps, one colour plus black, and information does the decorating. It fails when it's merely empty or when things sit off the grid.

**Editorial**
- What it is: a magazine feel, with a serif headline and sans text, varied column widths, pull quotes and large pictures.
- Choose it for: stories, thought pieces, founder letters, annual reviews, hospitality, premium brands.
- Top tier means: real typographic contrast, one picture cropped with intent, a clear reading path, generous margins, and copy worth reading. It fails when it looks like a template with stock photos.

**Quiet luxury**
- What it is: dark or pale grounds, a restrained palette, fine type, one material or metal accent, and very slow pacing.
- Choose it for: investment firms, private banks, premium property, high-end products.
- Top tier means: very few things on the page, exact alignment, one precious accent used once, and excellent figures. It fails with too much gold, drop shadows or any hurry.

**Data-led**
- What it is: the figure is the design, with large numbers, sorted charts and direct labels.
- Choose it for: analysis, board reviews, quarterly numbers, anything where a decision rests on a figure.
- Top tier means: one finding per view, one lit item, everything else muted, sources shown, and no chart junk. It fails on legends, rainbows and tiny labels.

**Bold poster**
- What it is: huge type, flat saturated colour, big shapes, type that crops or fills the page.
- Choose it for: campaigns, launches, events, sales, social posts that must stop a scroll.
- Top tier means: one idea readable in a second, confident scale, strong colour blocks, a shape with a real concept behind it. It fails when loud is all it has, or when it has too many things shouting.

**Brutalist**
- What it is: raw, system-like type, hard edges, visible structure, deliberate roughness.
- Choose it for: youth and culture brands, developer tools, studios, when the client wants to look unlike the category. Rarely right for finance, health or anything needing reassurance.
- Top tier means: the roughness is exact and intentional, the hierarchy is still clear, and it's still readable. It fails when it just looks unfinished.

**Warm and handmade**
- What it is: natural colours, friendly serif or rounded type, texture, real photos, small human details.
- Choose it for: cafes, food, neighbourhood shops, crafts, community.
- Top tier means: real pictures of the real thing, warmth from colour and words, slight imperfection on purpose, and still a clear hierarchy. It fails when it turns cute, cluttered or rustic clip art.

**Playful**
- What it is: rounded shapes, bright colours, characters, movement, surprising scale.
- Choose it for: consumer apps, kids, snacks, friendly launches.
- Top tier means: one simple graphic idea repeated with discipline, consistent corners and stroke, and still grown-up spacing. It fails when it's childish, or when every element is a different kind of fun.

**How to choose**
- Ask first: who's reading, what must they feel, and what's at stake? High stakes and money point to quiet luxury, data-led or Swiss. Attention and desire point to bold poster, playful or editorial. Warmth and trust in a person point to warm and handmade or editorial.
- Then check the kit: its voice and audience outrank your preference. If the kit names a style, use it. Use the same style across one job's deck, posters and posts, so a campaign looks like one thing.
- Then look for the unexpected right answer: inside the chosen style, do one thing a category competitor wouldn't. That's usually where a piece becomes memorable. Only one thing.

## Look before you hand it in

39. Look at every slide and graphic as a picture, with render_pictures, and run check_design. What do you see first, and is it what matters? Is anything crowded, clipped, touching an edge or too small to read at a glance?
40. Fix what you see, at most two rounds, then hand it in. Would a design director put their name on it?
41. Say which style you chose and why in one line with state_style, before you make anything, so the reviewer can judge the work against it. Your reply to foundry-desk stays as it is, with no style in it.
