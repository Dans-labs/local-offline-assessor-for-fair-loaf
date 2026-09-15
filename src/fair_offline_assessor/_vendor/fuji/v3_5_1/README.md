# F-UJI 3.5.1

Source files and SHA-256 digests are recorded in `upstream.json`.
The MIT license is included in `LICENSES/F-UJI-MIT.txt` at the project root.

- Evaluator code is unchanged except for the imports in `imports.patch`.
- `constants.py` contains only the original Mapper constants and offering-method
  enum required by this evaluator; it imports no collectors or preprocessors.
- `models.py` replaces the listed Swagger models with local dataclasses,
  preserving the F2 output fields and defaults. It provides no HTTP model parsing.

For an update, review the upstream differences, copy the required files/constants,
reapply the import changes and compare native results before selecting new metrics.
The caller removes empty fields, supplies the pinned definitions and creates
fresh evaluation state. Only F2 is connected; the other methods remain upstream code.
