# Native metadata support

The offline engine reuses the pinned F-UJI 3.5.1 readers and metric evaluators
from the original LOAF implementation. The public API accepts caller-supplied
metadata; it does not fetch the target identifier or remote resources.

Remote JSON-LD contexts must be supplied as local contexts or must match
packaged local mappings. Unsupported/irretrievable evidence is reflected in
assessment diagnostics and indeterminate metric outcomes.

Refer to `README.md` for the one-engine API and update process.
