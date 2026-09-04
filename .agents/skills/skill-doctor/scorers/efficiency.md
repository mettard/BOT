# Efficiency Rubric

Evaluate how efficiently the agent completed the task. Assign a score between 0.0 and 1.0.

- **0.0 - 0.3 (Poor)**: Agent looped on the same error multiple times, hallucinated tools, or required constant user intervention to proceed. Extreme token waste.
- **0.4 - 0.7 (Fair/Good)**: Agent made some mistakes, took unnecessary steps, or needed minor user corrections. Eventually reached the goal but could be optimized.
- **0.8 - 1.0 (Excellent)**: Agent completed the task directly, used tools appropriately, and handled expected errors gracefully on the first try. Minimum steps taken.
