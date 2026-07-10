# Idiom Lexicon Source

`idioms.json` is derived from the open-source `pwxcoo/chinese-xinhua`
idiom dataset:

- Source repository: https://github.com/pwxcoo/chinese-xinhua
- Source data: `data/idiom.json`
- License: MIT License, Copyright (c) 2018 PWXCOO

For the voice skill, the source records were converted to a compact local
format and filtered to four-Chinese-character idioms with four pinyin syllables.
Only `word`, `first_py`, and `last_py` are kept because the game only needs
tone-insensitive pronunciation matching.

