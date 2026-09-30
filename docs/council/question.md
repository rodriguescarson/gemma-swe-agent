Given everything in the CONTEXT, what is the best strategy for the remaining ~9 weeks to maximise our final (private) leaderboard score, with a stretch target of 0.20? Answer concretely:
1. Why do our heavier, locally better bundles (v9_eog 0.06, v10.1 0.08) score BELOW the simpler v4 (0.12 twice) on the hidden set, when local/pod evals ranked them equal or better? Give the most likely causes, ranked, and how to test each cheaply.
2. What should the next 3 bundles we submit be, and what exactly should change in each (agent structure, prompts, tools/helpers, budgets, thinking, temperature), and why?
3. How should we evaluate before spending a daily submission, given local evals have not predicted the hidden ranking? (We have: a golden stage-level eval suite, a proxy model on OpenRouter, pods with 2x H100, Kaggle 4xL4 30 h/week, and a Pallets hidden-like task set.)
4. Is LoRA fine-tuning (own trajectories or licence-permitted open-weight teacher trajectories) worth pursuing, and how?
5. What should we STOP doing?
Be specific and honest about uncertainty; respect every hard constraint in the CONTEXT.
