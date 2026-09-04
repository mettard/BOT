# Code Quality Rubric

Evaluate the quality of the code changes made by the agent. Assign a score between 0.0 and 1.0. If no code was written, use `insufficient_evidence`.

- **0.0 - 0.3 (Poor)**: Code introduced bugs, broke tests, or completely missed the user's requirements. Poor styling, lack of comments, or destructive changes without backups.
- **0.4 - 0.7 (Fair/Good)**: Code works but is not optimal. Might lack proper error handling, tests, or idiomatic patterns. Small regressions that are easy to fix.
- **0.8 - 1.0 (Excellent)**: Code is clean, idiomatic, robust, well-commented, and perfectly matches the user's requirements. Includes tests if applicable. Integrates flawlessly with the existing codebase.
