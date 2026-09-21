# Course-plan structured repair

1. Validate the initial `course_plan` result before any section-content work and ask the same structured task once to repair a missing or malformed plan.
2. Make the repair request name the required title, summary, and sections fields, include the original response and validation failure, and return a controlled error after a second invalid response.
3. Add regression coverage for successful repair and terminal invalid responses, then run the course-generation test set.
