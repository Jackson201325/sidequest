"""What counts as AI attribution in commits and PR text; ship-check and pr-body-check share it.
A human co-author is not attribution."""
import re

AI = re.compile(r"claude|codex|opencode|openai|anthropic|co-authored-by: .*(bot|ai)\b|generated (with|by)", re.I)
