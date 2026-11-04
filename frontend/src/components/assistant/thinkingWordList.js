// Decorative activity words while the assistant prepares an answer. They say
// nothing about what it is actually doing.
export const THINKING_WORDS = [
  "Accomplishing", "Actioning", "Actualizing", "Architecting", "Baking", "Beaming", "Beboppin'", "Befuddling",
  "Billowing", "Blanching", "Bloviating", "Boogieing", "Boondoggling", "Booping", "Bootstrapping", "Brewing",
  "Burrowing", "Calculating", "Canoodling", "Caramelizing", "Cascading", "Catapulting", "Cerebrating", "Channeling",
  "Choreographing", "Churning", "Coalescing", "Cogitating", "Combobulating", "Composing", "Computing", "Concocting",
  "Considering", "Contemplating", "Cooking", "Crafting", "Creating", "Crunching", "Crystallizing", "Cultivating",
  "Deciphering", "Deliberating", "Determining", "Dilly-dallying", "Discombobulating", "Doing", "Doodling",
  "Drizzling", "Ebbing", "Effecting", "Elucidating", "Embellishing", "Enchanting", "Envisioning", "Evaporating",
  "Fermenting", "Fiddle-faddling", "Finagling", "Flambeing", "Flibbertigibbeting", "Flowing", "Flummoxing",
  "Fluttering", "Forging", "Forming", "Frolicking", "Frosting", "Gallivanting", "Galloping", "Garnishing",
  "Generating", "Germinating", "Grooving", "Gusting", "Harmonizing", "Hashing", "Hatching", "Herding", "Honking",
  "Hullaballooing", "Hyperspacing", "Ideating", "Imagining", "Improvising", "Incubating", "Inferring", "Infusing",
  "Ionizing", "Jitterbugging", "Julienning", "Kneading", "Leavening", "Levitating", "Lollygagging", "Manifesting",
  "Marinating", "Meandering", "Metamorphosing", "Misting", "Moonwalking", "Moseying", "Mulling", "Mustering",
  "Musing", "Nebulizing", "Nesting", "Noodling", "Nucleating", "Orbiting", "Orchestrating", "Osmosing",
  "Perambulating", "Percolating", "Perusing", "Philosophising", "Photosynthesizing", "Pollinating", "Pondering",
  "Pontificating", "Pouncing", "Precipitating", "Prestidigitating", "Processing", "Proofing", "Propagating",
  "Puttering", "Puzzling", "Quantumizing", "Razzle-dazzling", "Razzmatazzing", "Recombobulating", "Reticulating",
  "Roosting", "Ruminating", "Sautéing", "Scampering", "Schlepping", "Scurrying", "Seasoning", "Shenaniganing",
  "Shimmying", "Simmering", "Skedaddling", "Sketching", "Slithering", "Smooshing", "Sock-hopping", "Spelunking",
  "Spinning", "Sprouting", "Stewing", "Sublimating", "Swirling", "Swooping", "Symbioting", "Synthesizing",
  "Tempering", "Thinking", "Thundering", "Tinkering", "Tomfoolering", "Topsy-turvying", "Transfiguring",
  "Transmuting", "Unfurling", "Unravelling", "Vibing", "Waddling", "Wandering", "Warping", "Whatchamacalliting",
  "Whirlpooling", "Whirring", "Whisking", "Wibbling", "Wrangling", "Zesting", "Zigzagging",
];

export const WORD_MS = 3000; // each word stays about three seconds, its reveal included
export const REVEAL_MS = 300; // the letters appear one by one, left to right, within this time
export const LEAVE_MS = 180; // the old word fades up and out, then the next one comes in

// The words in random order; a word comes back only after all the others, never twice in a row.
export function shuffled(last) {
  const deck = [...THINKING_WORDS];
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  if (deck[0] === last) deck.push(deck.shift());
  return deck;
}

